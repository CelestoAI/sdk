"""CLI commands for signing in to Celesto."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import keyring
import typer
from dotenv.main import DotEnv
from keyring.errors import KeyringError
from rich.console import Console
from typing_extensions import Annotated

from .sdk.client import _CelestoClient

DEFAULT_BASE_URL = "https://api.celesto.ai/v1"
KEYRING_SERVICE = "celesto"
CREDENTIALS_FILE_NAME = "credentials.json"
CREDENTIAL_STORE_PREFERENCE_KEY = "__credential_store_preference__"

app = typer.Typer(help="Sign in and manage saved credentials.")
console = Console()
# Warnings must never land on stdout: `--json` output is parsed by scripts and agents.
error_console = Console(stderr=True)

BaseUrlOption = Annotated[
    str,
    typer.Option(
        "--base-url",
        help="Celesto API URL",
        envvar="CELESTO_BASE_URL",
    ),
]


def _credential_account(base_url: str) -> str:
    return f"api_key:{base_url.rstrip('/')}"


def _resolve_base_url(base_url: str | None = None) -> str:
    return (base_url or os.environ.get("CELESTO_BASE_URL") or DEFAULT_BASE_URL).rstrip(
        "/"
    )


def _credential_file_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "celesto" / CREDENTIALS_FILE_NAME
    return Path.home() / ".config" / "celesto" / CREDENTIALS_FILE_NAME


def _load_file_credentials() -> dict[str, str]:
    """Load credentials from file, including the store preference marker."""
    credentials_path = _credential_file_path()
    if not credentials_path.exists():
        return {}

    try:
        data = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    credentials: dict[str, str] = {}
    for account, api_key in data.items():
        if isinstance(account, str) and isinstance(api_key, str):
            credentials[account] = api_key
    return credentials


def _save_file_credentials(credentials: dict[str, str]) -> None:
    credentials_path = _credential_file_path()
    credentials_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    credentials_path.parent.chmod(0o700)

    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=credentials_path.parent,
        delete=False,
    ) as temp_file:
        json.dump(credentials, temp_file, indent=2, sort_keys=True)
        temp_file.write("\n")
        temp_path = Path(temp_file.name)

    temp_path.chmod(0o600)
    temp_path.replace(credentials_path)


def _delete_file_credential(account: str) -> None:
    credentials = _load_file_credentials()
    if account not in credentials:
        return

    del credentials[account]
    credentials_path = _credential_file_path()
    if credentials:
        _save_file_credentials(credentials)
        return

    try:
        credentials_path.unlink()
    except FileNotFoundError:
        return


def _get_credential_store_preference(account: str) -> Literal["keyring", "file"] | None:
    """Get the preferred credential store for this account."""
    credentials = _load_file_credentials()
    pref_key = f"{CREDENTIAL_STORE_PREFERENCE_KEY}:{account}"
    pref = credentials.get(pref_key)
    if pref in ("keyring", "file"):
        return pref
    return None


def _set_credential_store_preference(
    account: str, store: Literal["keyring", "file"]
) -> None:
    """Record which credential store was last used successfully for this account."""
    credentials = _load_file_credentials()
    pref_key = f"{CREDENTIAL_STORE_PREFERENCE_KEY}:{account}"
    credentials[pref_key] = store
    _save_file_credentials(credentials)


def save_api_key(
    api_key: str, base_url: str | None = None
) -> Literal["keyring", "file"]:
    """Save an API key for future CLI commands."""
    resolved_base_url = _resolve_base_url(base_url)
    account = _credential_account(resolved_base_url)
    try:
        keyring.set_password(
            KEYRING_SERVICE,
            account,
            api_key,
        )
        _set_credential_store_preference(account, "keyring")
        return "keyring"
    except KeyringError:
        credentials = _load_file_credentials()
        credentials[account] = api_key
        _save_file_credentials(credentials)
        _set_credential_store_preference(account, "file")
        return "file"


def load_api_key_with_store(
    base_url: str | None = None,
) -> tuple[str | None, Literal["keyring", "file"] | None]:
    """Load a saved API key along with the store it came from.

    Returns (None, None) when no key is saved. Callers that need to tell the
    user *where* their credential came from should use this instead of
    load_api_key().
    """
    resolved_base_url = _resolve_base_url(base_url)
    account = _credential_account(resolved_base_url)

    # Check which store was last used successfully
    preference = _get_credential_store_preference(account)

    if preference == "file":
        # File was last used successfully, try file first
        file_key = _load_file_credentials().get(account)
        if file_key is not None:
            return file_key, "file"
        # Fall back to keyring if file doesn't have it
        try:
            keyring_key = keyring.get_password(KEYRING_SERVICE, account)
        except KeyringError:
            # The file preference is already missing; treat keyring failure as no saved key.
            return None, None
        return (keyring_key, "keyring") if keyring_key is not None else (None, None)

    # No preference or keyring preference: try keyring first
    try:
        saved_api_key = keyring.get_password(
            KEYRING_SERVICE,
            account,
        )
        if saved_api_key is not None:
            return saved_api_key, "keyring"
    except KeyringError:
        # Missing or unavailable keyring is expected on headless Linux; try file storage next.
        pass

    file_key = _load_file_credentials().get(account)
    return (file_key, "file") if file_key is not None else (None, None)


def load_api_key(base_url: str | None = None) -> str | None:
    """Load a saved API key for CLI commands."""
    api_key, _ = load_api_key_with_store(base_url)
    return api_key


def resolve_active_organization(
    api_key: str, base_url: str | None = None
) -> dict[str, str | None] | None:
    """Resolve the organization an API key acts on.

    Returns None when the organization cannot be determined (offline, revoked
    key, or an organization with no projects).
    """
    try:
        client = _CelestoClient(api_key=api_key, base_url=_resolve_base_url(base_url))
    except Exception:
        return None
    try:
        return client.organizations.active()
    except Exception:
        return None
    finally:
        client.close()


def describe_organization(organization: dict[str, str | None] | None) -> str:
    """Render an organization for display in prompts and status output."""
    if not organization:
        return "unknown"
    name = organization.get("name")
    organization_id = organization.get("id")
    if name and organization_id:
        return f"{name} ({organization_id})"
    return name or organization_id or "unknown"


CredentialOrigin = Literal["argument", "environment", "env_file", "saved"]

_ENV_FILE_OVERRIDE_WARNED = False


@dataclass(frozen=True)
class ResolvedCredential:
    """An API key plus the source it was resolved from."""

    api_key: str
    origin: CredentialOrigin
    env_file_path: Path | None = None
    saved_store: Literal["keyring", "file"] | None = None

    def describe_source(self) -> str:
        """Render the credential's source for status output and warnings."""
        if self.origin == "argument":
            return "the --api-key option"
        if self.origin == "environment":
            return "the CELESTO_API_KEY environment variable"
        if self.origin == "env_file":
            return f"the .env file at {self.env_file_path}"
        if self.saved_store == "file":
            return "your saved login (credentials file)"
        return "your saved login (system keyring)"


def _read_env_file_key(
    env_file: str | None = None, secret_name: str | None = None
) -> tuple[str | None, Path]:
    """Read an API key from a .env file, returning the key and the path tried."""
    dotenv_path = Path(env_file or ".env")
    dot_env = DotEnv(dotenv_path, verbose=False, encoding="utf-8")
    return dot_env.get(secret_name or "CELESTO_API_KEY"), dotenv_path


def _warn_if_env_file_overrides_saved_login(
    resolved: ResolvedCredential, base_url: str | None = None
) -> None:
    """Tell the user when a .env file silently outranks their saved login.

    API keys are bound to a single organization, so a stray .env in the working
    directory can point an otherwise identical command at a different tenant.
    Warn once per process, on stderr, and keep it network-free so it costs
    nothing on the hot path.

    Saved credentials are stored per API URL, so base_url has to match the
    endpoint the command targets or the comparison reads the wrong entry.
    """
    global _ENV_FILE_OVERRIDE_WARNED

    if resolved.origin != "env_file" or _ENV_FILE_OVERRIDE_WARNED:
        return

    saved_key, _ = load_api_key_with_store(base_url)
    if saved_key is None or saved_key == resolved.api_key:
        return

    _ENV_FILE_OVERRIDE_WARNED = True
    env_path = resolved.env_file_path
    resolved_path = env_path.resolve() if env_path is not None else Path(".env")
    error_console.print(
        f"[yellow]Warning:[/yellow] using the Celesto API key from {resolved_path}, "
        "which overrides your saved login."
    )
    error_console.print(
        "[dim]The two keys may target different organizations. "
        "Run `celesto auth status` to see which one this command uses.[/dim]"
    )


def resolve_cli_credential(
    api_key: str | None = None,
    ignore_env_file: bool | None = False,
    secret_name: str | None = None,
    warn_on_env_file_override: bool = True,
    base_url: str | None = None,
) -> ResolvedCredential | None:
    """Resolve the API key a CLI command will use, and where it came from.

    Precedence is unchanged: explicit argument, then CELESTO_API_KEY, then a
    .env file in the current working directory, then the saved login. Returns
    None when no key is found anywhere.

    Saved credentials are keyed by API URL, so callers that target a specific
    endpoint must pass base_url; otherwise the saved login for the default URL
    is used.

    Set warn_on_env_file_override=False when the caller prints its own, fuller
    explanation of the override (as `celesto auth status` does).
    """
    if api_key:
        return ResolvedCredential(api_key=api_key, origin="argument")

    env_key = os.environ.get(secret_name or "CELESTO_API_KEY")
    if env_key:
        return ResolvedCredential(api_key=env_key, origin="environment")

    if not ignore_env_file:
        env_file_key, env_file_path = _read_env_file_key(secret_name=secret_name)
        if env_file_key:
            resolved = ResolvedCredential(
                api_key=env_file_key,
                origin="env_file",
                env_file_path=env_file_path,
            )
            if warn_on_env_file_override:
                _warn_if_env_file_overrides_saved_login(resolved, base_url)
            return resolved

    if (secret_name or "CELESTO_API_KEY") == "CELESTO_API_KEY":
        saved_key, saved_store = load_api_key_with_store(base_url)
        if saved_key:
            return ResolvedCredential(
                api_key=saved_key, origin="saved", saved_store=saved_store
            )

    return None


def delete_api_key(base_url: str | None = None) -> None:
    """Delete a saved API key from both stores and clear the preference."""
    resolved_base_url = _resolve_base_url(base_url)
    account = _credential_account(resolved_base_url)

    # Delete from keyring
    try:
        keyring.delete_password(
            KEYRING_SERVICE,
            account,
        )
    except KeyringError:
        # Logout should still remove file credentials even when the OS keyring is unavailable.
        pass

    # Delete from file
    _delete_file_credential(account)

    # Clear the preference marker
    credentials = _load_file_credentials()
    pref_key = f"{CREDENTIAL_STORE_PREFERENCE_KEY}:{account}"
    if pref_key in credentials:
        del credentials[pref_key]
        if credentials:
            _save_file_credentials(credentials)
        else:
            # No more credentials, clean up the file
            try:
                _credential_file_path().unlink()
            except FileNotFoundError:
                pass


def validate_api_key(api_key: str, base_url: str | None = None) -> None:
    """Check that the API key can call Celesto."""
    client = _CelestoClient(api_key=api_key, base_url=_resolve_base_url(base_url))
    try:
        client.computers.list_templates()
    finally:
        client.close()


@app.command("login")
def login(
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            "-k",
            help="Celesto API key",
            prompt="Paste your Celesto API key",
            hide_input=True,
        ),
    ] = None,
    base_url: BaseUrlOption = DEFAULT_BASE_URL,
):
    """Save your Celesto API key for future CLI commands."""
    if not api_key:
        console.print("No API key was provided. Run celesto auth login.")
        raise typer.Exit(1)

    resolved_base_url = _resolve_base_url(base_url)
    try:
        validate_api_key(api_key, resolved_base_url)
    except Exception as exc:
        console.print(
            "That API key did not work. Check it and run celesto auth login again."
        )
        raise typer.Exit(1) from exc

    try:
        credential_store = save_api_key(api_key, resolved_base_url)
    except OSError as exc:
        console.print(
            "Your API key could not be saved. Set CELESTO_API_KEY and try your command again."
        )
        raise typer.Exit(1) from exc

    if credential_store == "file":
        console.print(
            "Saved your Celesto API key in a local credentials file. You can now run commands like celesto computer list."
        )
    else:
        console.print(
            "Saved your Celesto API key. You can now run commands like celesto computer list."
        )


@app.command("status")
def status(base_url: BaseUrlOption = DEFAULT_BASE_URL):
    """Show which API key CLI commands use, and the organization it targets."""
    resolved_base_url = _resolve_base_url(base_url)
    resolved = resolve_cli_credential(
        warn_on_env_file_override=False, base_url=resolved_base_url
    )

    if resolved is None:
        console.print("No saved API key was found. Run celesto auth login.")
        return

    console.print(f"API URL:      {resolved_base_url}")
    console.print(f"Credential:   {resolved.describe_source()}")

    organization = resolve_active_organization(resolved.api_key, resolved_base_url)
    console.print(f"Organization: {describe_organization(organization)}")

    if resolved.origin == "env_file":
        saved_key, saved_store = load_api_key_with_store(resolved_base_url)
        if saved_key is not None and saved_key != resolved.api_key:
            store_label = (
                "credentials file" if saved_store == "file" else "system keyring"
            )
            console.print()
            console.print(
                f"[yellow]This .env key overrides your saved login ({store_label}).[/yellow]"
            )
            saved_organization = resolve_active_organization(
                saved_key, resolved_base_url
            )
            console.print(
                f"[dim]Your saved login targets {describe_organization(saved_organization)}.[/dim]"
            )
            console.print(
                "[dim]Commands run from this directory use the .env key. "
                "Run from another directory, or pass --api-key, to use your saved login.[/dim]"
            )


@app.command("token", hidden=True)
def token(base_url: BaseUrlOption = DEFAULT_BASE_URL):
    """Return a saved API key to trusted local integrations."""
    resolved_base_url = _resolve_base_url(base_url)
    api_key = load_api_key(resolved_base_url)
    if not api_key:
        typer.echo(
            "No saved API key was found. Run celesto auth login.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(api_key)


@app.command("logout")
def logout(base_url: BaseUrlOption = DEFAULT_BASE_URL):
    """Remove your saved Celesto API key."""
    resolved_base_url = _resolve_base_url(base_url)
    delete_api_key(resolved_base_url)
    console.print(
        "Removed your saved Celesto API key. Run celesto auth login to sign in again."
    )
