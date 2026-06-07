"""CLI commands for signing in to Celesto."""

from __future__ import annotations

import os

import keyring
import typer
from keyring.errors import KeyringError
from rich.console import Console
from typing_extensions import Annotated

from .sdk.client import Celesto

DEFAULT_BASE_URL = "https://api.celesto.ai/v1"
KEYRING_SERVICE = "celesto"

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


def save_api_key(api_key: str, base_url: str | None = None) -> None:
    """Save an API key in the operating system's secure credential store."""
    resolved_base_url = _resolve_base_url(base_url)
    keyring.set_password(
        KEYRING_SERVICE,
        _credential_account(resolved_base_url),
        api_key,
    )


def load_api_key(base_url: str | None = None) -> str | None:
    """Load a saved API key from the operating system's secure credential store."""
    resolved_base_url = _resolve_base_url(base_url)
    try:
        return keyring.get_password(
            KEYRING_SERVICE,
            _credential_account(resolved_base_url),
        )
    except KeyringError:
        return None


def delete_api_key(base_url: str | None = None) -> None:
    """Delete a saved API key from the operating system's secure credential store."""
    resolved_base_url = _resolve_base_url(base_url)
    try:
        keyring.delete_password(
            KEYRING_SERVICE,
            _credential_account(resolved_base_url),
        )
    except KeyringError:
        return


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
        console.print("That API key did not work. Check it and run celesto auth login again.")
        raise typer.Exit(1) from exc

    try:
        save_api_key(api_key, resolved_base_url)
    except KeyringError as exc:
        console.print(
            "Your API key could not be saved securely. Set CELESTO_API_KEY and try your command again."
        )
        raise typer.Exit(1) from exc

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
