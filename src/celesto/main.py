from __future__ import annotations

import typer
from rich import print

from . import computer

app = typer.Typer(
    help="Infrastructure for sandboxes and computer-use agents.",
    no_args_is_help=True,
)
app.add_typer(computer.app, name="computer")


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
