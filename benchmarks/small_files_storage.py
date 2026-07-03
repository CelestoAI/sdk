"""Benchmark small-file writes on Celesto's mounted persistent home.

This benchmark creates or reuses a Celesto computer, starts a tiny HTTP server
inside that computer, and downloads many small files from localhost into the
mounted target directory. Serving from localhost keeps public internet bandwidth
out of the measurement, so the result focuses on per-file download, metadata,
and write behavior.

Examples:
    uv run python benchmarks/small_files_storage.py --files 5000 --size-bytes 4096
    uv run python benchmarks/small_files_storage.py --files 10000 --concurrency 32 --compare-root
    uv run python benchmarks/small_files_storage.py --computer curie --keep-target --json
"""

from __future__ import annotations

import argparse
import base64
import json
import shlex
import time
from typing import Any

from dotenv import find_dotenv, load_dotenv

from celesto import Computer

DEFAULT_PERSISTENT_TARGET = "/home/ohm"
DEFAULT_TARGET_SUBDIR = "celesto-small-files-benchmark"
DEFAULT_ROOT_TARGET = "/tmp/celesto-small-files-benchmark"


REMOTE_SCRIPT = r"""
from __future__ import annotations

import concurrent.futures
import functools
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Any


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def file_relpath(index: int, fanout: int) -> pathlib.Path:
    name = f"file_{index:08d}.bin"
    if fanout <= 1:
        return pathlib.Path(name)
    return pathlib.Path(f"dir_{index % fanout:04d}") / name


def create_source_files(source_dir: pathlib.Path, *, files: int, size_bytes: int, fanout: int) -> dict[str, Any]:
    start = time.perf_counter()
    shutil.rmtree(source_dir, ignore_errors=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    # Deterministic payload, varied by index byte to avoid a completely empty sparse-looking workload.
    base_payload = bytes((i % 251 for i in range(size_bytes)))
    relpaths: list[str] = []
    for index in range(files):
        relpath = file_relpath(index, fanout)
        path = source_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        if size_bytes:
            payload = bytes([(base_payload[0] + index) % 251]) + base_payload[1:]
        else:
            payload = b""
        path.write_bytes(payload)
        relpaths.append(relpath.as_posix())

    return {
        "seconds": time.perf_counter() - start,
        "source_dir": str(source_dir),
        "relpaths": relpaths,
    }


def df_info(path: pathlib.Path) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["df", "-PT", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        lines = [line.split() for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) >= 2 and len(lines[1]) >= 7:
            row = lines[1]
            return {
                "filesystem": row[0],
                "type": row[1],
                "size_1k": int(row[2]),
                "used_1k": int(row[3]),
                "available_1k": int(row[4]),
                "use_percent": row[5],
                "mounted_on": row[6],
            }
    except Exception as exc:
        return {"error": str(exc)}
    return {}


def mount_info(path: pathlib.Path) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["findmnt", "-T", str(path), "-J", "-o", "SOURCE,FSTYPE,TARGET,OPTIONS"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            parsed = json.loads(completed.stdout)
            filesystems = parsed.get("filesystems") or []
            if filesystems:
                return filesystems[0]
    except Exception as exc:
        return {"error": str(exc)}
    return {}


def juicefs_processes() -> list[str]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid,args"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if "juicefs" in line.lower()]


def download_one(
    *,
    base_url: str,
    relpath: str,
    target_dir: pathlib.Path,
    expected_size: int,
    fsync: bool,
    request_timeout: float,
) -> float:
    quoted = urllib.parse.quote(relpath)
    url = f"{base_url}/{quoted}"
    destination = target_dir / relpath
    destination.parent.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    with urllib.request.urlopen(url, timeout=request_timeout) as response:
        data = response.read()
    if len(data) != expected_size:
        raise RuntimeError(f"{relpath} downloaded {len(data)} bytes, expected {expected_size}")
    with destination.open("wb") as file:
        file.write(data)
        if fsync:
            file.flush()
            os.fsync(file.fileno())
    return time.perf_counter() - start


def benchmark_target(
    *,
    label: str,
    target_dir: pathlib.Path,
    relpaths: list[str],
    size_bytes: int,
    concurrency: int,
    fsync: bool,
    keep_target: bool,
    base_url: str,
    request_timeout: float,
) -> dict[str, Any]:
    cleanup_before_start = time.perf_counter()
    shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    cleanup_before_seconds = time.perf_counter() - cleanup_before_start

    before_df = df_info(target_dir)
    before_mount = mount_info(target_dir)
    start = time.perf_counter()
    worker = functools.partial(
        download_one,
        base_url=base_url,
        target_dir=target_dir,
        expected_size=size_bytes,
        fsync=fsync,
        request_timeout=request_timeout,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        latencies = list(executor.map(lambda relpath: worker(relpath=relpath), relpaths))
    download_seconds = time.perf_counter() - start
    after_df = df_info(target_dir)
    after_mount = mount_info(target_dir)

    delete_seconds = None
    if not keep_target:
        delete_start = time.perf_counter()
        shutil.rmtree(target_dir, ignore_errors=True)
        delete_seconds = time.perf_counter() - delete_start

    total_bytes = len(relpaths) * size_bytes
    return {
        "label": label,
        "target_dir": str(target_dir),
        "before_df": before_df,
        "after_df": after_df,
        "before_mount": before_mount,
        "after_mount": after_mount,
        "files": len(relpaths),
        "size_bytes": size_bytes,
        "total_bytes": total_bytes,
        "concurrency": concurrency,
        "fsync": fsync,
        "cleanup_before_seconds": cleanup_before_seconds,
        "download_seconds": download_seconds,
        "files_per_second": len(relpaths) / download_seconds if download_seconds > 0 else 0.0,
        "mib_per_second": (total_bytes / 1024 / 1024) / download_seconds if download_seconds > 0 else 0.0,
        "per_file_ms": {
            "min": min(latencies) * 1000 if latencies else 0.0,
            "p50": percentile(latencies, 0.50) * 1000,
            "p95": percentile(latencies, 0.95) * 1000,
            "max": max(latencies) * 1000 if latencies else 0.0,
        },
        "delete_seconds": delete_seconds,
    }


def path_is_within(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def validate_required_mount(target: pathlib.Path, require_mount: str | None) -> None:
    if not require_mount:
        return
    mount = pathlib.Path(require_mount)
    if not path_is_within(target, mount):
        return
    if not mount.exists():
        raise RuntimeError(f"Required mount path does not exist: {mount}")
    if not os.path.ismount(mount):
        raise RuntimeError(f"Required mount path is not mounted: {mount}")


def run(args: dict[str, Any]) -> dict[str, Any]:
    files = int(args["files"])
    size_bytes = int(args["size_bytes"])
    fanout = int(args["fanout"])
    concurrency = int(args["concurrency"])
    if files <= 0:
        raise ValueError("files must be greater than 0")
    if size_bytes < 0:
        raise ValueError("size_bytes must be 0 or greater")
    if concurrency <= 0:
        raise ValueError("concurrency must be greater than 0")

    source_dir = pathlib.Path(args["source_dir"])
    source = create_source_files(source_dir, files=files, size_bytes=size_bytes, fanout=fanout)
    relpaths = source.pop("relpaths")

    handler = functools.partial(QuietHandler, directory=str(source_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        persistent_target = pathlib.Path(args["target"])
        validate_required_mount(persistent_target, args.get("require_mount"))
        target_subdir = str(args.get("target_subdir") or "")
        effective_persistent_target = (
            persistent_target / target_subdir if target_subdir else persistent_target
        )
        targets: list[tuple[str, pathlib.Path]] = [
            ("persistent", effective_persistent_target)
        ]
        if args.get("compare_root"):
            targets.append(("root", pathlib.Path(args["root_target"])))

        target_results = [
            benchmark_target(
                label=label,
                target_dir=target,
                relpaths=relpaths,
                size_bytes=size_bytes,
                concurrency=concurrency,
                fsync=bool(args.get("fsync")),
                keep_target=bool(args.get("keep_target")),
                base_url=base_url,
                request_timeout=float(args["request_timeout"]),
            )
            for label, target in targets
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if not args.get("keep_source"):
            shutil.rmtree(source_dir, ignore_errors=True)

    return {
        "config": {
            "files": files,
            "size_bytes": size_bytes,
            "fanout": fanout,
            "concurrency": concurrency,
            "source_dir": str(source_dir),
            "target": args["target"],
            "target_subdir": args.get("target_subdir"),
            "compare_root": bool(args.get("compare_root")),
            "fsync": bool(args.get("fsync")),
            "keep_target": bool(args.get("keep_target")),
            "require_mount": args.get("require_mount"),
        },
        "source_prepare": source,
        "targets": target_results,
        "juicefs_processes": juicefs_processes(),
    }


def main() -> None:
    args_json = os.environ.get("CELESTO_SMALL_FILE_BENCHMARK_ARGS")
    args_file = os.environ.get("CELESTO_SMALL_FILE_BENCHMARK_ARGS_FILE")
    if args_json is None and args_file:
        args_json = pathlib.Path(args_file).read_text(encoding="utf-8")
    if args_json is None:
        raise RuntimeError("Benchmark arguments were not provided.")
    args = json.loads(args_json)
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    main()
"""


def wait_for_running(
    computer: Computer, *, timeout: float = 180, poll: float = 2
) -> None:
    """Wait until a Celesto computer reaches running state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if computer.status == "running":
            return
        if computer.status == "stopped":
            computer.start()
        time.sleep(poll)
        computer.refresh()
    raise TimeoutError(
        f"Computer {computer.get('name')} did not become running within {timeout}s "
        f"(last status: {computer.status})."
    )


def run_checked(
    computer: Computer,
    command: str,
    *,
    timeout: int,
    label: str,
) -> dict[str, Any]:
    """Run a remote command and raise a useful error if it fails."""
    result = computer.run(command, timeout=timeout)
    if result.get("exit_code") != 0:
        raise RuntimeError(
            f"{label} failed with exit code {result.get('exit_code')}.\n"
            f"STDOUT:\n{result.get('stdout', '')}\nSTDERR:\n{result.get('stderr', '')}"
        )
    return result


def upload_text_file(
    computer: Computer,
    *,
    content: str,
    remote_path: str,
    timeout: int,
    chunk_size: int = 3000,
) -> None:
    """Upload text to the computer without sending one oversized exec command."""
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    b64_path = f"{remote_path}.b64"
    quoted_b64_path = shlex.quote(b64_path)
    run_checked(
        computer,
        f"rm -f {quoted_b64_path} {shlex.quote(remote_path)}",
        timeout=30,
        label=f"cleanup {remote_path}",
    )

    for index in range(0, len(encoded), chunk_size):
        chunk = encoded[index : index + chunk_size]
        run_checked(
            computer,
            f"cat >> {quoted_b64_path} <<'EOF'\n{chunk}\nEOF",
            timeout=30,
            label=f"upload chunk {index // chunk_size + 1} for {remote_path}",
        )

    decode_command = (
        "python3 - <<'PY'\n"
        "import base64, pathlib\n"
        f"pathlib.Path({remote_path!r}).write_bytes("
        f"base64.b64decode(pathlib.Path({b64_path!r}).read_text()))\n"
        "PY"
    )
    run_checked(
        computer,
        decode_command,
        timeout=30,
        label=f"decode {remote_path}",
    )


def prepare_remote_benchmark(
    computer: Computer,
    *,
    remote_args: dict[str, Any],
    timeout: int,
) -> tuple[str, str]:
    """Upload the embedded benchmark script and its arguments."""
    script_path = "/tmp/celesto_small_files_storage_benchmark.py"
    args_path = "/tmp/celesto_small_files_storage_args.json"
    upload_text_file(
        computer,
        content=REMOTE_SCRIPT,
        remote_path=script_path,
        timeout=timeout,
    )
    upload_text_file(
        computer,
        content=json.dumps(remote_args),
        remote_path=args_path,
        timeout=timeout,
    )
    return script_path, args_path


def parse_remote_json(stdout: str) -> dict[str, Any]:
    """Parse JSON even when streamed exec prefixes output with transport markers."""
    stripped = stdout.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(parsed, dict):
            return parsed

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise json.JSONDecodeError("No JSON object found in remote stdout", stdout, 0)


def run_remote_benchmark(
    computer: Computer,
    *,
    remote_args: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    """Run the remote small-file benchmark and parse its JSON output."""
    script_path, args_path = prepare_remote_benchmark(
        computer,
        remote_args=remote_args,
        timeout=timeout,
    )
    command = (
        f"CELESTO_SMALL_FILE_BENCHMARK_ARGS_FILE={shlex.quote(args_path)} "
        f"python3 {shlex.quote(script_path)}"
    )
    result = run_checked(
        computer,
        command,
        timeout=timeout,
        label="remote benchmark",
    )
    stdout = result.get("stdout", "")
    try:
        return parse_remote_json(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Remote benchmark did not return JSON.\nSTDOUT:\n{stdout}\nSTDERR:\n{result.get('stderr', '')}"
        ) from exc


def print_result(result: dict[str, Any]) -> None:
    """Print a human-readable benchmark summary."""
    config = result["config"]
    print("\nCelesto small-file storage benchmark")
    print("=" * 44)
    print(f"Files:       {config['files']}")
    print(f"Size/file:   {config['size_bytes']} bytes")
    print(f"Fanout dirs: {config['fanout']}")
    print(f"Concurrency: {config['concurrency']}")
    print(f"Source prep: {result['source_prepare']['seconds']:.3f}s")

    juicefs_processes = result.get("juicefs_processes") or []
    if juicefs_processes:
        print("\nJuiceFS process:")
        for process in juicefs_processes[:3]:
            print(f"  {process[:220]}")

    for target in result["targets"]:
        per_file = target["per_file_ms"]
        print(f"\n{target['label']}: {target['target_dir']}")
        filesystem = target.get("before_df", {}).get("filesystem")
        mounted_on = target.get("before_df", {}).get("mounted_on")
        if filesystem or mounted_on:
            print(
                f"  Filesystem: {filesystem or 'unknown'} on {mounted_on or 'unknown'}"
            )
        mount_options = target.get("before_mount", {}).get("options")
        if mount_options:
            print(f"  Mount opts: {str(mount_options)[:220]}")
        print(f"  Download:   {target['download_seconds']:.3f}s")
        print(f"  Throughput: {target['files_per_second']:.1f} files/s")
        print(f"  Bandwidth:  {target['mib_per_second']:.2f} MiB/s")
        print(
            "  Per file:   "
            f"p50={per_file['p50']:.2f}ms "
            f"p95={per_file['p95']:.2f}ms "
            f"max={per_file['max']:.2f}ms"
        )
        if target.get("delete_seconds") is not None:
            print(f"  Delete:     {target['delete_seconds']:.3f}s")


def main() -> None:
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)

    parser = argparse.ArgumentParser(
        description=(
            "Download many small files inside a Celesto computer to benchmark "
            "the mounted persistent-home filesystem."
        )
    )
    parser.add_argument("--computer", help="Existing Celesto computer name or ID")
    parser.add_argument("--base-url", help="Celesto API base URL")
    parser.add_argument(
        "--cpus", type=int, default=1, help="vCPUs when creating a computer"
    )
    parser.add_argument(
        "--memory", type=int, default=1024, help="Memory in MB when creating a computer"
    )
    parser.add_argument(
        "--disk", default="4gb", help="Disk size when creating a computer"
    )
    parser.add_argument(
        "--template",
        default="coding-agent",
        help="Template ID when creating a computer",
    )
    parser.add_argument(
        "--keep-computer",
        action="store_true",
        help="Do not delete a computer created by this benchmark",
    )
    parser.add_argument(
        "--files", type=int, default=5000, help="Number of small files to download"
    )
    parser.add_argument("--size-bytes", type=int, default=4096, help="Bytes per file")
    parser.add_argument(
        "--fanout",
        type=int,
        default=100,
        help="Number of subdirectories to spread files across; use 1 for one directory",
    )
    parser.add_argument(
        "--concurrency", type=int, default=32, help="Concurrent download workers"
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_PERSISTENT_TARGET,
        help="Persistent target root inside the computer",
    )
    parser.add_argument(
        "--target-subdir",
        default=DEFAULT_TARGET_SUBDIR,
        help="Benchmark subdirectory under --target; pass an empty string to write directly under --target",
    )
    parser.add_argument(
        "--source-dir",
        default="/tmp/celesto-small-files-source",
        help="Temporary source directory inside the computer",
    )
    parser.add_argument(
        "--require-mount",
        default=DEFAULT_PERSISTENT_TARGET,
        help="Require this path to be mounted before writing under it; pass an empty string to disable",
    )
    parser.add_argument(
        "--compare-root",
        action="store_true",
        help="Also run the same benchmark against the root disk under /tmp",
    )
    parser.add_argument(
        "--root-target", default=DEFAULT_ROOT_TARGET, help="Root-disk comparison target"
    )
    parser.add_argument(
        "--fsync",
        action="store_true",
        help="Call fsync after each downloaded file write",
    )
    parser.add_argument(
        "--keep-target", action="store_true", help="Keep downloaded files after the run"
    )
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="Keep generated source files under --source-dir",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=30,
        help="Per-file localhost HTTP timeout in seconds",
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=300,
        help="Remote command timeout in seconds. Celesto accepts up to 300 seconds.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=180,
        help="Seconds to wait for the computer to be running",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON result")
    args = parser.parse_args()
    if args.command_timeout > 300:
        parser.error("--command-timeout must be 300 seconds or less")

    created_computer = args.computer is None
    computer: Computer | None = None
    try:
        if args.computer:
            computer = Computer.get(args.computer, base_url=args.base_url)
        else:
            computer = Computer(
                cpus=args.cpus,
                memory=args.memory,
                disk=args.disk,
                template_id=args.template,
                base_url=args.base_url,
            )

        wait_for_running(computer, timeout=args.wait_timeout)
        remote_args = {
            "files": args.files,
            "size_bytes": args.size_bytes,
            "fanout": args.fanout,
            "concurrency": args.concurrency,
            "target": args.target,
            "target_subdir": args.target_subdir,
            "source_dir": args.source_dir,
            "compare_root": args.compare_root,
            "root_target": args.root_target,
            "require_mount": args.require_mount,
            "fsync": args.fsync,
            "keep_target": args.keep_target,
            "keep_source": args.keep_source,
            "request_timeout": args.request_timeout,
        }
        result = run_remote_benchmark(
            computer,
            remote_args=remote_args,
            timeout=args.command_timeout,
        )
        result["computer"] = {
            "id": computer.id,
            "name": computer.name,
            "created_by_benchmark": created_computer,
        }

        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_result(result)
    finally:
        if computer is not None:
            if created_computer and not args.keep_computer:
                computer.delete()
            computer.close()


if __name__ == "__main__":
    main()
