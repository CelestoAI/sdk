"""CLI commands for signing in to Celesto."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import keyring
import typer
from rich.console import Console
from typing_extensions import Annotated

from .sdk.client import Celesto

DEFAULT_BASE_URL = "https://api.celesto.ai/v1"
KEYRING_SERVICE = "celesto"
CREDENTIALS_FILE_NAME = "credentials.json"

app = typer.Typer(help="Sign in and manage saved credentials.")
console = Console()

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
        return "keyring"
    except Exception:
        credentials = _load_file_credentials()
        credentials[account] = api_key
        _save_file_credentials(credentials)
        return "file"


def load_api_key(base_url: str | None = None) -> str | None:
    """Load a saved API key for CLI commands."""
    resolved_base_url = _resolve_base_url(base_url)
    account = _credential_account(resolved_base_url)
    try:
        saved_api_key = keyring.get_password(
            KEYRING_SERVICE,
            account,
        )
        if saved_api_key is not None:
            return saved_api_key
    except Exception:
        pass

    return _load_file_credentials().get(account)


def delete_api_key(base_url: str | None = None) -> None:
    """Delete a saved API key for CLI commands."""
    resolved_base_url = _resolve_base_url(base_url)
    account = _credential_account(resolved_base_url)
    try:
        keyring.delete_password(
            KEYRING_SERVICE,
            account,
        )
    except Exception:
        pass
    _delete_file_credential(account)


def validate_api_key(api_key: str, base_url: str | None = None) -> None:
    """Check that the API key can call Celesto."""
    client = Celesto(api_key=api_key, base_url=_resolve_base_url(base_url))
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
    """Show whether a Celesto API key is saved."""
    resolved_base_url = _resolve_base_url(base_url)
    if load_api_key(resolved_base_url):
        console.print(
            f"A Celesto API key is saved for {resolved_base_url}. Run celesto auth logout to remove it."
        )
        return

    console.print("No saved API key was found. Run celesto auth login.")


@app.command("logout")
def logout(base_url: BaseUrlOption = DEFAULT_BASE_URL):
    """Remove your saved Celesto API key."""
    resolved_base_url = _resolve_base_url(base_url)
    delete_api_key(resolved_base_url)
    console.print(
        "Removed your saved Celesto API key. Run celesto auth login to sign in again."
    )
