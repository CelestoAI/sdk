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

app = typer.Typer(help="Create, manage, and connect to sandboxed computers.")
console = Console()

# Common option types
ApiKeyOption = Annotated[
    Optional[str],
    typer.Option("--api-key", "-k", help="Celesto API key"),
]
JsonOption = Annotated[
    bool,
    typer.Option("--json", "-j", help="Output as JSON (for machines and AI agents)"),
]


def _get_client(api_key: str | None = None) -> CelestoSDK:
    """Create SDK client with resolved API key."""
    key = _get_api_key(api_key)
    return CelestoSDK(api_key=key)


def _status_color(status: str) -> str:
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


def _format_memory(mb: int) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.0f} GB"
    return f"{mb} MB"


def _print_json(data: object) -> None:
    """Print JSON to stdout (no Rich formatting)."""
    sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")


@app.command("create")
def create_computer(
    cpus: Annotated[
        int, typer.Option("--cpus", "-c", help="Number of virtual CPUs")
    ] = 1,
    memory: Annotated[int, typer.Option("--memory", "-m", help="Memory in MB")] = 1024,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Create a new sandboxed computer."""
    with _get_client(api_key) as client:
        if not as_json:
            console.print("Creating computer...", style="dim")
        result = client.computers.create(cpus=cpus, memory=memory)

    if as_json:
        _print_json(result)
        return

    cname = result.get("name", "")
    cid = result["id"]
    status = result["status"]
    color = _status_color(status)

    console.print(f"  Name:   [bold]{cname}[/bold]")
    console.print(f"  ID:     [dim]{cid}[/dim]")
    console.print(f"  Status: [{color}]{status}[/{color}]")
    console.print(f"  CPUs:   {cpus}")
    console.print(f"  Memory: {_format_memory(memory)}")
    console.print()
    console.print(f"[dim]Connect with:[/dim] celesto computer ssh {cname}")


@app.command("list")
def list_computers(
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """List all computers."""
    with _get_client(api_key) as client:
        result = client.computers.list()

    computers = result.get("computers", [])

    if as_json:
        _print_json(computers)
        return

    if not computers:
        console.print("[dim]No computers found. Create one with:[/dim]")
        console.print("  celesto computer create")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Status")
    table.add_column("CPUs", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("Created")

    for c in computers:
        color = _status_color(c["status"])
        table.add_row(
            c.get("name", ""),
            c["id"],
            f"[{color}]{c['status']}[/{color}]",
            str(c["vcpus"]),
            _format_memory(c["ram_mb"]),
            c.get("created_at", "")[:19],
        )

    console.print(table)


@app.command("run")
def run_command(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    command: Annotated[str, typer.Argument(help="Command to execute")],
    timeout: Annotated[
        int, typer.Option("--timeout", "-t", help="Timeout in seconds")
    ] = 30,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Execute a command on a computer. Automatically resumes stopped computers."""
    import time

    from .sdk.exceptions import CelestoServerError

    with _get_client(api_key) as client:
        try:
            result = client.computers.exec(computer_id, command, timeout=timeout)
        except CelestoServerError as e:
            if "stopped" in str(e).lower() or "409" in str(e):
                if not as_json:
                    console.print(f"[yellow]Computer is stopped. Resuming...[/yellow]")
                client.computers.start(computer_id)
                # Wait for it to be running
                for _ in range(30):
                    info = client.computers.get(computer_id)
                    if info.get("status") == "running":
                        break
                    time.sleep(1)
                else:
                    console.print("[red]Computer failed to resume.[/red]")
                    raise typer.Exit(1)
                if not as_json:
                    console.print("[green]Computer resumed.[/green]")
                result = client.computers.exec(computer_id, command, timeout=timeout)
            else:
                raise

    if as_json:
        _print_json(result)
        return

    if result.get("stdout"):
        sys.stdout.write(result["stdout"])
    if result.get("stderr"):
        sys.stderr.write(result["stderr"])

    raise typer.Exit(result.get("exit_code", 0))


@app.command("ssh")
def ssh_to_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    api_key: ApiKeyOption = None,
):
    """Open an interactive terminal session on a computer. Automatically resumes stopped computers."""
    import os
    import signal
    import termios
    import threading
    import time
    import tty

    import websockets.sync.client

    key = _get_api_key(api_key)

    # Check if computer is stopped and auto-resume
    with _get_client(api_key) as client:
        info = client.computers.get(computer_id)
        resolved_id = info.get("id", computer_id)
        if info.get("status") == "stopped":
            console.print(f"[yellow]Computer is stopped. Resuming...[/yellow]")
            client.computers.start(resolved_id)
            for _ in range(30):
                info = client.computers.get(resolved_id)
                if info.get("status") == "running":
                    break
                time.sleep(1)
            else:
                console.print("[red]Computer failed to resume.[/red]")
                raise typer.Exit(1)
            console.print("[green]Computer resumed.[/green]")

    base_url = os.environ.get("CELESTO_BASE_URL", "https://api.celesto.ai/v1")
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/computers/{resolved_id}/terminal"

    console.print(f"[dim]Connecting to {computer_id}...[/dim]")

    try:
        ws = websockets.sync.client.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {key}"},
        )
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {e}")
        raise typer.Exit(1)

    ws.send(json.dumps({"token": key}))

    rows, cols = os.get_terminal_size()
    ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))

    console.print("[dim]Connected. Press Ctrl+] to disconnect.[/dim]")

    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)
    done = threading.Event()

    def recv_loop():
        try:
            while not done.is_set():
                try:
                    msg = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                if isinstance(msg, str):
                    os.write(sys.stdout.fileno(), msg.encode("utf-8"))
                elif isinstance(msg, bytes):
                    os.write(sys.stdout.fileno(), msg)
        except websockets.exceptions.ConnectionClosed as e:
            if e.rcvd and e.rcvd.code != 1000:
                console.print(f"\n[red]Connection closed: code={e.rcvd.code} reason={e.rcvd.reason}[/red]")
        except OSError:
            pass
        finally:
            done.set()

    def handle_sigwinch(*_args):
        nonlocal rows, cols
        try:
            new_rows, new_cols = os.get_terminal_size()
            if (new_rows, new_cols) != (rows, cols):
                rows, cols = new_rows, new_cols
                ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))
        except Exception:
            pass

    try:
        tty.setraw(stdin_fd)
        old_sigwinch = signal.signal(signal.SIGWINCH, handle_sigwinch)

        receiver = threading.Thread(target=recv_loop, daemon=True)
        receiver.start()

        while not done.is_set():
            try:
                data = os.read(stdin_fd, 4096)
            except OSError:
                break
            if not data:
                break
            if b"\x1d" in data:
                break
            try:
                ws.send(data.decode("utf-8", errors="replace"))
            except (websockets.exceptions.ConnectionClosed, OSError):
                break

    except KeyboardInterrupt:
        pass
    finally:
        done.set()
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        signal.signal(signal.SIGWINCH, old_sigwinch)
        try:
            ws.close()
        except Exception:
            pass
        console.print("\n[dim]Disconnected.[/dim]")


@app.command("stop")
def stop_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Stop a running computer."""
    with _get_client(api_key) as client:
        result = client.computers.stop(computer_id)

    if as_json:
        _print_json(result)
        return

    console.print(f"[dim]Computer {computer_id} is being stopped.[/dim]")


@app.command("start")
def start_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Start a stopped computer."""
    with _get_client(api_key) as client:
        result = client.computers.start(computer_id)

    if as_json:
        _print_json(result)
        return

    console.print(f"[dim]Computer {computer_id} is being started.[/dim]")


@app.command("delete")
def delete_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Skip confirmation")
    ] = False,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Delete a computer."""
    if not force and not as_json:
        confirm = typer.confirm(f"Delete computer {computer_id}?")
        if not confirm:
            raise typer.Abort()

    with _get_client(api_key) as client:
        result = client.computers.delete(computer_id)

    if as_json:
        _print_json(result)
        return

    console.print(f"[dim]Computer {computer_id} is being deleted.[/dim]")
