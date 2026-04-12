"""CLI commands for managing sandboxed computers."""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

from .deployment import _get_api_key
from .sdk.client import CelestoSDK

app = typer.Typer(help="Manage sandboxed computers.")
console = Console()


def _get_client(api_key: str | None = None) -> CelestoSDK:
    """Create SDK client with resolved API key."""
    key = _get_api_key(api_key)
    return CelestoSDK(api_key=key)


def _status_color(status: str) -> str:
    """Get Rich color for a status."""
    colors = {
        "creating": "yellow",
        "running": "green",
        "stopping": "yellow",
        "stopped": "dim",
        "starting": "yellow",
        "deleting": "yellow",
        "deleted": "dim",
        "error": "red",
    }
    return colors.get(status, "white")


def _format_ram(ram_mb: int) -> str:
    if ram_mb >= 1024:
        return f"{ram_mb / 1024:.0f} GB"
    return f"{ram_mb} MB"


@app.command("create")
def create_computer(
    name: Annotated[
        Optional[str],
        typer.Option("--name", "-n", help="Friendly name for the computer"),
    ] = None,
    cpus: Annotated[
        int,
        typer.Option("--cpus", "-c", help="Number of virtual CPUs"),
    ] = 1,
    memory: Annotated[
        int,
        typer.Option("--memory", "-m", help="Memory in MB"),
    ] = 1024,
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", "-k", help="Celesto API key"),
    ] = None,
):
    """Create a new sandboxed computer."""
    with _get_client(api_key) as client:
        console.print("Creating computer...", style="dim")
        result = client.computers.create(vcpus=cpus, ram_mb=memory)

    cid = result["id"]
    status = result["status"]
    color = _status_color(status)

    if name:
        console.print(f"  Name:   {name}")
    console.print(f"  ID:     [bold]{cid}[/bold]")
    console.print(f"  Status: [{color}]{status}[/{color}]")
    console.print(f"  CPUs:   {cpus}")
    console.print(f"  Memory: {_format_ram(memory)}")
    console.print()
    console.print(f"[dim]Connect with:[/dim] celesto computer ssh {cid}")


@app.command("list")
def list_computers(
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", "-k", help="Celesto API key"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output format: table or json"),
    ] = "table",
):
    """List all computers."""
    with _get_client(api_key) as client:
        result = client.computers.list()

    computers = result.get("computers", [])

    if output == "json":
        console.print_json(json.dumps(computers))
        return

    if not computers:
        console.print("[dim]No computers found. Create one with:[/dim]")
        console.print("  celesto computer create")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("CPUs", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("Created")

    for c in computers:
        color = _status_color(c["status"])
        table.add_row(
            c["id"],
            f"[{color}]{c['status']}[/{color}]",
            str(c["vcpus"]),
            _format_ram(c["ram_mb"]),
            c.get("created_at", "")[:19],
        )

    console.print(table)


@app.command("run")
def run_command(
    computer_id: Annotated[
        str,
        typer.Argument(help="Computer ID or name"),
    ],
    command: Annotated[
        str,
        typer.Argument(help="Command to execute"),
    ],
    timeout: Annotated[
        int,
        typer.Option("--timeout", "-t", help="Timeout in seconds"),
    ] = 30,
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", "-k", help="Celesto API key"),
    ] = None,
):
    """Execute a command on a computer."""
    with _get_client(api_key) as client:
        result = client.computers.exec(computer_id, command, timeout=timeout)

    # Print stdout
    if result.get("stdout"):
        sys.stdout.write(result["stdout"])

    # Print stderr to stderr
    if result.get("stderr"):
        sys.stderr.write(result["stderr"])

    # Exit with the command's exit code
    raise typer.Exit(result.get("exit_code", 0))


@app.command("ssh")
def ssh_to_computer(
    computer_id: Annotated[
        str,
        typer.Argument(help="Computer ID or name"),
    ],
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", "-k", help="Celesto API key"),
    ] = None,
):
    """Open an interactive terminal session on a computer."""
    import os
    import select
    import termios
    import tty

    import websockets.sync.client

    key = _get_api_key(api_key)

    # Build WebSocket URL
    base_url = os.environ.get("CELESTO_BASE_URL", "https://api.celesto.ai/v1")
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/computers/{computer_id}/terminal"

    console.print(f"[dim]Connecting to {computer_id}...[/dim]")

    try:
        ws = websockets.sync.client.connect(ws_url)
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {e}")
        raise typer.Exit(1)

    # Send auth
    ws.send(json.dumps({"token": key, "org_id": _resolve_org_id(key)}))

    # Get terminal size
    rows, cols = os.get_terminal_size()
    ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))

    # Switch terminal to raw mode
    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)

    console.print("[dim]Connected. Press Ctrl+] to disconnect.[/dim]")

    try:
        tty.setraw(stdin_fd)
        ws.socket.setblocking(False)

        while True:
            # Check for input from stdin or websocket
            readable, _, _ = select.select([stdin_fd, ws.socket], [], [], 0.05)

            for fd in readable:
                if fd == stdin_fd:
                    data = os.read(stdin_fd, 4096)
                    if not data:
                        return
                    # Ctrl+] to disconnect
                    if b"\x1d" in data:
                        return
                    ws.send(data.decode("utf-8", errors="replace"))
                else:
                    try:
                        msg = ws.recv(timeout=0)
                        if isinstance(msg, str):
                            os.write(sys.stdout.fileno(), msg.encode("utf-8"))
                        elif isinstance(msg, bytes):
                            os.write(sys.stdout.fileno(), msg)
                    except TimeoutError:
                        pass
                    except websockets.exceptions.ConnectionClosed:
                        return

            # Handle terminal resize
            try:
                new_rows, new_cols = os.get_terminal_size()
                if (new_rows, new_cols) != (rows, cols):
                    rows, cols = new_rows, new_cols
                    ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))
            except OSError:
                pass

    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        try:
            ws.close()
        except Exception:
            pass
        console.print("\n[dim]Disconnected.[/dim]")


@app.command("delete")
def delete_computer(
    computer_id: Annotated[
        str,
        typer.Argument(help="Computer ID or name"),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", "-k", help="Celesto API key"),
    ] = None,
):
    """Delete a computer."""
    if not force:
        confirm = typer.confirm(f"Delete computer {computer_id}?")
        if not confirm:
            raise typer.Abort()

    with _get_client(api_key) as client:
        client.computers.delete(computer_id)

    console.print(f"[dim]Computer {computer_id} is being deleted.[/dim]")


def _resolve_org_id(api_key: str) -> str:
    """Resolve org ID from API key by calling user info endpoint."""
    import os

    import httpx

    base_url = os.environ.get("CELESTO_BASE_URL", "https://api.celesto.ai/v1")
    try:
        resp = httpx.get(
            f"{base_url}/users/info",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # Return the default org or first org
        return data.get("default_organization_id", data.get("organization_id", ""))
    except Exception:
        return ""
