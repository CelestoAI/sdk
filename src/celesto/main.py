from __future__ import annotations

import subprocess
import sys
from shutil import which

import typer
from rich import print

from . import auth, computer

app = typer.Typer(
    help="Infrastructure for sandboxes and computer-use agents.",
    no_args_is_help=True,
)
app.add_typer(auth.app, name="auth")
app.add_typer(computer.app, name="computer")


def _has_pip() -> bool:
    return (
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _run_update() -> None:
    if _has_pip():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "celesto"],
            check=True,
        )
        return

    uv = which("uv")
    if uv is None:
        raise RuntimeError(
            "This Python environment does not have pip. "
            "Install pip or run uv pip install --python "
            f"{sys.executable} --upgrade celesto."
        )

    print("pip is not installed in this environment. Using uv instead...")
    subprocess.run(  # noqa: S603
        [uv, "pip", "install", "--python", sys.executable, "--upgrade", "celesto"],
        check=True,
    )


@app.command("update")
def update() -> None:
    """Update Celesto to the newest version available from pip."""
    print("Checking for a newer Celesto version...")
    try:
        _run_update()
    except subprocess.CalledProcessError:
        print(
            "[red]Could not update Celesto. "
            f"Run uv pip install --python {sys.executable} --upgrade celesto.[/red]"
        )
        raise typer.Exit(1) from None
    except RuntimeError as exc:
        print(f"[red]{exc}[/red]")
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
