"""OpenAI Agents SDK sandbox providers for Celesto.

This module lets ``agents.sandbox.SandboxAgent`` run against either:

- Celesto hosted computers, through the Celesto API.
- Local SmolVM sandboxes, through the optional ``smolvm`` package.

The OpenAI Agents SDK treats sandbox providers as pluggable clients and
sessions. These classes implement that provider boundary while keeping the
agent harness and model calls outside the sandbox.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import shlex
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

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
        "Celesto OpenAI Agents integration requires the optional dependency "
        "'openai-agents'. Install it with: pip install 'celesto[openai-agents]'"
    ) from exc

from celesto.sdk.client import Celesto

_DEFAULT_TIMEOUT_S = 30
_CHUNK_SIZE = 48 * 1024


def _timeout_seconds(timeout: float | None, default: int = _DEFAULT_TIMEOUT_S) -> int:
    if timeout is None:
        return default
    return max(1, math.ceil(timeout))


def _coerce_bytes(data: io.IOBase, *, path: Path) -> bytes:
    payload = data.read()
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    try:
        return bytes(payload)
    except TypeError as exc:
        raise TypeError(f"Could not read bytes for {path}.") from exc


class _CommandBackedSession(BaseSandboxSession):
    """Shared file/workspace behavior for command-only sandbox backends."""

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
        # The SDK may probe before the workspace exists. Only cd after it is ready.
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
            raise RuntimeError(result.get("stderr") or f"Could not write {remote_path}.")

    async def _write_bytes(self, path: Path, payload: bytes) -> None:
        workspace_path = self.normalize_path(path, for_write=True)
        await self._write_remote_bytes(workspace_path.as_posix(), payload)

    async def read(self, path: Path, *, user: str | User | None = None) -> io.IOBase:
        _ = user
        workspace_path = self.normalize_path(path)
        quoted = shlex.quote(workspace_path.as_posix())
        result = await self._run_guest(f"test -r {quoted} && base64 < {quoted}")
        if result.get("exit_code") != 0:
            raise FileNotFoundError(workspace_path.as_posix())
        return io.BytesIO(base64.b64decode(result.get("stdout", "").encode("utf-8")))

    async def write(
        self,
        path: Path,
        data: io.IOBase,
        *,
        user: str | User | None = None,
    ) -> None:
        _ = user
        await self._write_bytes(path, _coerce_bytes(data, path=path))

    async def running(self) -> bool:
        return self._running

    async def persist_workspace(self) -> io.IOBase:
        root = shlex.quote(self.state.manifest.root)
        result = await self._run_guest(
            f"test -d {root} && cd {root} && tar -cf - . | base64",
            timeout=120,
        )
        if result.get("exit_code") != 0:
            raise RuntimeError(result.get("stderr") or "Could not persist workspace.")
        return io.BytesIO(base64.b64decode(result.get("stdout", "").encode("utf-8")))

    async def hydrate_workspace(self, data: io.IOBase) -> None:
        remote_tar = f"/tmp/celesto-openai-agents-{uuid.uuid4().hex}.tar"
        await self._write_remote_bytes(remote_tar, _coerce_bytes(data, path=Path(remote_tar)))
        root = shlex.quote(self.state.manifest.root)
        quoted_tar = shlex.quote(remote_tar)
        result = await self._run_guest(
            f"mkdir -p {root} && tar -xf {quoted_tar} -C {root} && rm -f {quoted_tar}",
            timeout=120,
        )
        if result.get("exit_code") != 0:
            raise RuntimeError(result.get("stderr") or "Could not hydrate workspace.")


class CelestoSandboxClientOptions(BaseSandboxClientOptions):
    """Options for hosted Celesto computers used by ``SandboxAgent``."""

    type: Literal["celesto"] = "celesto"
    computer_id: str | None = None
    cpus: int = 1
    memory: int = 1024
    image: str = "ubuntu-desktop-24.04"
    delete_on_close: bool | None = None


class CelestoSandboxSessionState(SandboxSessionState):
    """Serializable state for a hosted Celesto sandbox session."""

    type: Literal["celesto"] = "celesto"
    computer_id: str | None = None
    cpus: int = 1
    memory: int = 1024
    image: str = "ubuntu-desktop-24.04"
    delete_on_close: bool = True


class CelestoSandboxSession(_CommandBackedSession):
    """OpenAI Agents SDK session backed by a hosted Celesto computer."""

    state: CelestoSandboxSessionState

    def __init__(self, *, state: CelestoSandboxSessionState, client: Celesto) -> None:
        self.state = state
        self._client = client
        self._running = False

    @classmethod
    def from_state(
        cls,
        state: CelestoSandboxSessionState,
        *,
        client: Celesto,
    ) -> "CelestoSandboxSession":
        return cls(state=state, client=client)

    async def _ensure_backend_started(self) -> None:
        if self.state.computer_id is None:
            created = await asyncio.to_thread(
                self._client.computers.create,
                cpus=self.state.cpus,
                memory=self.state.memory,
                image=self.state.image,
            )
            self.state.computer_id = created["id"]
            return

        info = await asyncio.to_thread(self._client.computers.get, self.state.computer_id)
        if info.get("status") == "stopped":
            await asyncio.to_thread(self._client.computers.start, self.state.computer_id)

    async def _shutdown_backend(self) -> None:
        if self.state.computer_id is None:
            return
        with suppress(Exception):
            await asyncio.to_thread(self._client.computers.stop, self.state.computer_id)
        self._running = False

    async def _run_guest(self, command: str, *, timeout: float | None = None) -> dict[str, Any]:
        if self.state.computer_id is None:
            raise RuntimeError("Celesto computer is not created yet.")
        return await asyncio.to_thread(
            self._client.computers.exec,
            self.state.computer_id,
            command,
            timeout=_timeout_seconds(timeout),
        )

    async def _delete_backend(self) -> None:
        if self.state.computer_id is None:
            return
        if self.state.delete_on_close:
            with suppress(Exception):
                await asyncio.to_thread(self._client.computers.delete, self.state.computer_id)
        self._running = False


class CelestoSandboxClient(BaseSandboxClient[CelestoSandboxClientOptions | None]):
    """OpenAI Agents SDK sandbox client for hosted Celesto computers."""

    backend_id = "celesto"
    supports_default_options = True

    def __init__(
        self,
        *,
        client: Celesto | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._client = client or Celesto(api_key=api_key, base_url=base_url)

    async def create(
        self,
        *,
        snapshot: SnapshotSpec | SnapshotBase | None = None,
        manifest: Manifest | None = None,
        options: CelestoSandboxClientOptions | None = None,
    ) -> SandboxSession:
        resolved = options or CelestoSandboxClientOptions()
        manifest = manifest or Manifest()
        session_id = uuid.uuid4()
        created_by_client = resolved.computer_id is None
        delete_on_close = (
            created_by_client if resolved.delete_on_close is None else resolved.delete_on_close
        )
        state = CelestoSandboxSessionState(
            session_id=session_id,
            manifest=manifest,
            snapshot=resolve_snapshot(snapshot, str(session_id)),
            computer_id=resolved.computer_id,
            cpus=resolved.cpus,
            memory=resolved.memory,
            image=resolved.image,
            delete_on_close=delete_on_close,
        )
        inner = CelestoSandboxSession.from_state(state, client=self._client)
        return self._wrap_session(inner)

    async def delete(self, session: SandboxSession) -> SandboxSession:
        inner = session._inner
        if not isinstance(inner, CelestoSandboxSession):
            raise TypeError("CelestoSandboxClient.delete expects a CelestoSandboxSession")
        await inner._delete_backend()
        return session

    async def resume(self, state: SandboxSessionState) -> SandboxSession:
        if not isinstance(state, CelestoSandboxSessionState):
            raise TypeError("CelestoSandboxClient.resume expects a CelestoSandboxSessionState")
        inner = CelestoSandboxSession.from_state(state, client=self._client)
        inner._set_start_state_preserved(True)
        return self._wrap_session(inner)

    def deserialize_session_state(self, payload: dict[str, object]) -> SandboxSessionState:
        return CelestoSandboxSessionState.model_validate(payload)


class SmolVMSandboxClientOptions(BaseSandboxClientOptions):
    """Options for local SmolVM sandboxes used by ``SandboxAgent``."""

    type: Literal["smolvm"] = "smolvm"
    vm_id: str | None = None
    os: str | None = None
    backend: str | None = None
    memory: int | None = None
    disk_size: int | None = None
    exposed_ports: tuple[int, ...] = ()
    delete_on_close: bool | None = None


class SmolVMSandboxSessionState(SandboxSessionState):
    """Serializable state for a local SmolVM sandbox session."""

    type: Literal["smolvm"] = "smolvm"
    vm_id: str | None = None
    os: str | None = None
    backend: str | None = None
    memory: int | None = None
    disk_size: int | None = None
    delete_on_close: bool = True


class SmolVMSandboxSession(_CommandBackedSession):
    """OpenAI Agents SDK session backed by one local SmolVM VM."""

    state: SmolVMSandboxSessionState

    def __init__(self, *, state: SmolVMSandboxSessionState) -> None:
        self.state = state
        self._vm: Any | None = None
        self._running = False

    @classmethod
    def from_state(cls, state: SmolVMSandboxSessionState) -> "SmolVMSandboxSession":
        return cls(state=state)

    def _import_smolvm(self) -> Any:
        try:
            from smolvm import SmolVM
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "SmolVM sandbox support requires the optional dependency 'smolvm'. "
                "Install it with: pip install 'celesto[openai-agents-smolvm]'"
            ) from exc
        return SmolVM

    def _connect_or_create_vm(self) -> Any:
        if self._vm is not None:
            return self._vm

        SmolVM = self._import_smolvm()
        if self.state.vm_id:
            self._vm = SmolVM.from_id(self.state.vm_id, backend=self.state.backend)
        else:
            self._vm = SmolVM(
                os=self.state.os,
                backend=self.state.backend,
                memory=self.state.memory,
                disk_size=self.state.disk_size,
            )
            self.state.vm_id = self._vm.vm_id
        return self._vm

    async def _ensure_backend_started(self) -> None:
        vm = self._connect_or_create_vm()
        await asyncio.to_thread(vm.start)
        self.state.vm_id = vm.vm_id

    async def _shutdown_backend(self) -> None:
        if self._vm is None:
            return
        with suppress(Exception):
            await asyncio.to_thread(self._vm.stop)
        self._running = False

    async def _run_guest(self, command: str, *, timeout: float | None = None) -> dict[str, Any]:
        vm = self._connect_or_create_vm()
        result = await asyncio.to_thread(
            vm.run,
            command,
            timeout=_timeout_seconds(timeout),
        )
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}

    async def _resolve_exposed_port(self, port: int) -> ExposedPortEndpoint:
        vm = self._connect_or_create_vm()
        host_port = await asyncio.to_thread(vm.expose_local, port)
        return ExposedPortEndpoint(host="127.0.0.1", port=host_port, tls=False)

    async def write(
        self,
        path: Path,
        data: io.IOBase,
        *,
        user: str | User | None = None,
    ) -> None:
        _ = user
        workspace_path = self.normalize_path(path, for_write=True)
        payload = _coerce_bytes(data, path=path)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        try:
            vm = self._connect_or_create_vm()
            await asyncio.to_thread(vm.upload_file, tmp_path, workspace_path.as_posix())
        finally:
            tmp_path.unlink(missing_ok=True)

    async def running(self) -> bool:
        if self._vm is None and self.state.vm_id is None:
            return False
        try:
            vm = self._connect_or_create_vm()
            await asyncio.to_thread(vm.refresh)
            return getattr(vm.status, "value", str(vm.status)) == "running"
        except Exception:
            return self._running

    async def _delete_backend(self) -> None:
        vm = self._vm
        if vm is None and self.state.vm_id:
            with suppress(Exception):
                SmolVM = self._import_smolvm()
                vm = SmolVM.from_id(self.state.vm_id, backend=self.state.backend)
        if vm is None:
            return
        with suppress(Exception):
            await asyncio.to_thread(vm.stop)
        if self.state.delete_on_close:
            with suppress(Exception):
                await asyncio.to_thread(vm.delete)
        self._vm = None
        self._running = False


class SmolVMSandboxClient(BaseSandboxClient[SmolVMSandboxClientOptions | None]):
    """OpenAI Agents SDK sandbox client for local SmolVM sandboxes."""

    backend_id = "smolvm"
    supports_default_options = True

    async def create(
        self,
        *,
        snapshot: SnapshotSpec | SnapshotBase | None = None,
        manifest: Manifest | None = None,
        options: SmolVMSandboxClientOptions | None = None,
    ) -> SandboxSession:
        resolved = options or SmolVMSandboxClientOptions()
        manifest = manifest or Manifest()
        session_id = uuid.uuid4()
        created_by_client = resolved.vm_id is None
        delete_on_close = (
            created_by_client if resolved.delete_on_close is None else resolved.delete_on_close
        )
        state = SmolVMSandboxSessionState(
            session_id=session_id,
            manifest=manifest,
            snapshot=resolve_snapshot(snapshot, str(session_id)),
            vm_id=resolved.vm_id,
            os=resolved.os,
            backend=resolved.backend,
            memory=resolved.memory,
            disk_size=resolved.disk_size,
            exposed_ports=resolved.exposed_ports,
            delete_on_close=delete_on_close,
        )
        inner = SmolVMSandboxSession.from_state(state)
        return self._wrap_session(inner)

    async def delete(self, session: SandboxSession) -> SandboxSession:
        inner = session._inner
        if not isinstance(inner, SmolVMSandboxSession):
            raise TypeError("SmolVMSandboxClient.delete expects a SmolVMSandboxSession")
        await inner._delete_backend()
        return session

    async def resume(self, state: SandboxSessionState) -> SandboxSession:
        if not isinstance(state, SmolVMSandboxSessionState):
            raise TypeError("SmolVMSandboxClient.resume expects a SmolVMSandboxSessionState")
        inner = SmolVMSandboxSession.from_state(state)
        inner._set_start_state_preserved(True)
        return self._wrap_session(inner)

    def deserialize_session_state(self, payload: dict[str, object]) -> SandboxSessionState:
        return SmolVMSandboxSessionState.model_validate(payload)


__all__ = [
    "CelestoSandboxClient",
    "CelestoSandboxClientOptions",
    "CelestoSandboxSession",
    "CelestoSandboxSessionState",
    "SmolVMSandboxClient",
    "SmolVMSandboxClientOptions",
    "SmolVMSandboxSession",
    "SmolVMSandboxSessionState",
]
