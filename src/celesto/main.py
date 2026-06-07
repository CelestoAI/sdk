from __future__ import annotations

import subprocess
import sys

import typer
from rich import print

from . import auth, computer

app = typer.Typer(
    help="Infrastructure for sandboxes and computer-use agents.",
    no_args_is_help=True,
)
app.add_typer(auth.app, name="auth")
app.add_typer(computer.app, name="computer")


def _run_pip_update() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "celesto"],
        check=True,
    )


@app.command("update")
def update() -> None:
    """Update Celesto to the newest version available from pip."""
    print("Checking for a newer Celesto version...")
    try:
        _run_pip_update()
    except subprocess.CalledProcessError:
        print(
            "[red]Could not update Celesto. "
            "Run python -m pip install --upgrade celesto.[/red]"
        )
        raise typer.Exit(1) from None
    print("Celesto is up to date or has been updated.")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        print(
            """[orange_red1]
    ╭──────────────────────────────────────────────────────────────────────╮
    │      Infrastructure for sandboxes and computer-use agents.           │
    │                    [bold][link=https://celesto.ai]https://celesto.ai[/link][/bold]                              │
    ╰──────────────────────────────────────────────────────────────────────╯
[/orange_red1]
"""
        )
        typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()
