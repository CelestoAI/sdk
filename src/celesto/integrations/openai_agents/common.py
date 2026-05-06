"""Shared helpers for OpenAI agents that use Celesto computers.

Most users should import `CelestoSandboxClient` or `SmolVMSandboxClient` from
`celesto.integrations.openai_agents`. This module keeps the common file and
command behavior in one place.
"""

from __future__ import annotations

import base64
import io
import math
import shlex
import uuid
from pathlib import Path
from typing import Any

try:
    from agents.sandbox import Manifest
    from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
    from agents.sandbox.session.sandbox_client import (
        BaseSandboxClient,
        BaseSandboxClientOptions,
    )
    from agents.sandbox.session.sandbox_session import SandboxSession
    from agents.sandbox.session.sandbox_session_state import SandboxSessionState
    from agents.sandbox.snapshot import SnapshotBase, SnapshotSpec, resolve_snapshot
    from agents.sandbox.types import ExecResult, ExposedPortEndpoint, User
except ImportError as exc:  # pragma: no cover - depends on optional extra
    raise ImportError(
        "OpenAI Agents support is not installed. Run "
        "`pip install 'celesto[openai-agents]'` and try again."
    ) from exc

_DEFAULT_TIMEOUT_S = 30
_CHUNK_SIZE = 48 * 1024


def timeout_seconds(timeout: float | None, default: int = _DEFAULT_TIMEOUT_S) -> int:
    """Return a safe command timeout in whole seconds."""
    if timeout is None:
        return default
    return max(1, math.ceil(timeout))


def coerce_bytes(data: io.IOBase, *, path: Path) -> bytes:
    """Read bytes from a file-like object."""
    payload = data.read()
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    try:
        return bytes(payload)
    except TypeError as exc:
        raise TypeError(
            f"Could not read file data for {path}. Pass a readable file object."
        ) from exc


class CommandBackedSession(BaseSandboxSession):
    """Common file behavior for sandboxes that run shell commands."""

    async def _run_guest(self, command: str, *, timeout: float | None = None) -> Any:
        raise NotImplementedError

    async def _manifest_environment_exports(self) -> str:
        environment = await self.state.manifest.environment.resolve()
        return "; ".join(
            f"export {key}={shlex.quote(value)}" for key, value in environment.items()
        )

    async def _prepare_backend_workspace(self) -> None:
        await self._run_guest(
            f"mkdir -p -- {shlex.quote(self.state.manifest.root)}",
            timeout=30,
        )

    async def _after_start(self) -> None:
        self._running = True

    async def _after_stop(self) -> None:
        self._running = False

    async def _exec_internal(
        self,
        *command: str | Path,
        timeout: float | None = None,
    ) -> ExecResult:
        root = shlex.quote(self.state.manifest.root)
        exports = await self._manifest_environment_exports()
        command_text = shlex.join(str(part) for part in command)
        script_parts = []
        if exports:
            script_parts.append(exports)
        # The OpenAI runner may check the computer before files are ready.
        script_parts.append(f"if [ -d {root} ]; then cd {root}; fi")
        script_parts.append(command_text)
        result = await self._run_guest("; ".join(script_parts), timeout=timeout)
        return ExecResult(
            stdout=result["stdout"].encode("utf-8", errors="replace"),
            stderr=result["stderr"].encode("utf-8", errors="replace"),
            exit_code=int(result["exit_code"]),
        )

    async def _write_remote_bytes(self, remote_path: str, payload: bytes) -> None:
        quoted_path = shlex.quote(remote_path)
        parent = shlex.quote(str(Path(remote_path).parent))
        b64_path = shlex.quote(f"/tmp/celesto-openai-agents-{uuid.uuid4().hex}.b64")

        await self._run_guest(f"mkdir -p -- {parent} && : > {b64_path}")
        encoded = base64.b64encode(payload).decode("ascii")
        try:
            for start in range(0, len(encoded), _CHUNK_SIZE):
                chunk = encoded[start : start + _CHUNK_SIZE]
                await self._run_guest(
                    "cat >> "
                    f"{b64_path} <<'CELESTO_OPENAI_AGENTS_B64'\n"
                    f"{chunk}\n"
                    "CELESTO_OPENAI_AGENTS_B64"
                )
            result = await self._run_guest(
                f"base64 -d {b64_path} > {quoted_path} && rm -f {b64_path}",
                timeout=120,
            )
        finally:
            await self._run_guest(f"rm -f {b64_path}")

        if result.get("exit_code") != 0:
            raise RuntimeError(
                result.get("stderr")
                or (
                    f"Could not write file in the sandbox: {remote_path}. "
                    "Check the path or choose a writable folder."
                )
            )

    async def _write_bytes(self, path: Path, payload: bytes) -> None:
        workspace_path = self.normalize_path(path, for_write=True)
        await self._write_remote_bytes(workspace_path.as_posix(), payload)

    async def read(self, path: Path, *, user: str | User | None = None) -> io.IOBase:
        _ = user
        workspace_path = self.normalize_path(path)
        quoted = shlex.quote(workspace_path.as_posix())
        result = await self._run_guest(f"test -r {quoted} && base64 < {quoted}")
        if result.get("exit_code") != 0:
            raise FileNotFoundError(
                f"File is missing in the sandbox: {workspace_path.as_posix()}. "
                "Check the path or create the file before reading it."
            )
        return io.BytesIO(base64.b64decode(result.get("stdout", "").encode("utf-8")))

    async def write(
        self,
        path: Path,
        data: io.IOBase,
        *,
        user: str | User | None = None,
    ) -> None:
        _ = user
        await self._write_bytes(path, coerce_bytes(data, path=path))

    async def running(self) -> bool:
        return self._running

    async def persist_workspace(self) -> io.IOBase:
        root = shlex.quote(self.state.manifest.root)
        result = await self._run_guest(
            f"test -d {root} && cd {root} && tar -cf - . | base64",
            timeout=120,
        )
        if result.get("exit_code") != 0:
            raise RuntimeError(
                result.get("stderr")
                or "Could not save sandbox files. Create a new session and try again."
            )
        return io.BytesIO(base64.b64decode(result.get("stdout", "").encode("utf-8")))

    async def hydrate_workspace(self, data: io.IOBase) -> None:
        remote_tar = f"/tmp/celesto-openai-agents-{uuid.uuid4().hex}.tar"
        await self._write_remote_bytes(remote_tar, coerce_bytes(data, path=Path(remote_tar)))
        root = shlex.quote(self.state.manifest.root)
        quoted_tar = shlex.quote(remote_tar)
        result = await self._run_guest(
            f"mkdir -p {root} && tar -xf {quoted_tar} -C {root} && rm -f {quoted_tar}",
            timeout=120,
        )
        if result.get("exit_code") != 0:
            raise RuntimeError(
                result.get("stderr")
                or "Could not restore sandbox files. Create a new session and try again."
            )


__all__ = [
    "BaseSandboxClient",
    "BaseSandboxClientOptions",
    "CommandBackedSession",
    "ExposedPortEndpoint",
    "Manifest",
    "SandboxSession",
    "SandboxSessionState",
    "SnapshotBase",
    "SnapshotSpec",
    "User",
    "coerce_bytes",
    "resolve_snapshot",
    "timeout_seconds",
]
