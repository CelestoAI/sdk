"""Run OpenAI agents on local SmolVM sandboxes.

Use this module when you want an OpenAI ``SandboxAgent`` to work on your own
machine without giving it direct access to your files or shell.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from celesto.integrations.openai_agents.common import (
    BaseSandboxClient,
    BaseSandboxClientOptions,
    CommandBackedSession,
    ExposedPortEndpoint,
    Manifest,
    SandboxSession,
    SandboxSessionState,
    SnapshotBase,
    SnapshotSpec,
    User,
    coerce_bytes,
    resolve_snapshot,
    timeout_seconds,
)


class SmolVMSandboxClientOptions(BaseSandboxClientOptions):
    """Settings for running a ``SandboxAgent`` on local SmolVM."""

    type: Literal["smolvm"] = "smolvm"
    vm_id: str | None = None
    os: str | None = None
    backend: str | None = None
    memory: int | None = None
    disk_size: int | None = None
    exposed_ports: tuple[int, ...] = ()
    delete_on_close: bool | None = None


class SmolVMSandboxSessionState(SandboxSessionState):
    """Information needed to reconnect to a local SmolVM sandbox later."""

    type: Literal["smolvm"] = "smolvm"
    vm_id: str | None = None
    os: str | None = None
    backend: str | None = None
    memory: int | None = None
    disk_size: int | None = None
    delete_on_close: bool = True


class SmolVMSandboxSession(CommandBackedSession):
    """A running OpenAI agent workspace on local SmolVM."""

    state: SmolVMSandboxSessionState

    def __init__(self, *, state: SmolVMSandboxSessionState) -> None:
        self.state = state
        self._vm: Any | None = None
        self._running = False
        self._command_lock = asyncio.Lock()

    @classmethod
    def from_state(cls, state: SmolVMSandboxSessionState) -> "SmolVMSandboxSession":
        return cls(state=state)

    def _import_smolvm(self) -> Any:
        try:
            from smolvm import SmolVM
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "SmolVM support is not installed. Run "
                "`pip install 'celesto[openai-agents]'` and try again."
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
        async with self._command_lock:
            result = await asyncio.to_thread(
                vm.run,
                command,
                timeout=timeout_seconds(timeout),
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
        payload = coerce_bytes(data, path=path)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        try:
            vm = self._connect_or_create_vm()
            async with self._command_lock:
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
    """Create and manage local SmolVM sandboxes for OpenAI agents."""

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
            raise TypeError(
                "Wrong session type. Use SmolVMSandboxClient with SmolVMSandboxSession."
            )
        await inner._delete_backend()
        return session

    async def resume(self, state: SandboxSessionState) -> SandboxSession:
        if not isinstance(state, SmolVMSandboxSessionState):
            raise TypeError(
                "Wrong saved session type. Use SmolVMSandboxClient with "
                "SmolVMSandboxSessionState."
            )
        inner = SmolVMSandboxSession.from_state(state)
        inner._set_start_state_preserved(True)
        return self._wrap_session(inner)

    def deserialize_session_state(self, payload: dict[str, object]) -> SandboxSessionState:
        return SmolVMSandboxSessionState.model_validate(payload)


__all__ = [
    "SmolVMSandboxClient",
    "SmolVMSandboxClientOptions",
    "SmolVMSandboxSession",
    "SmolVMSandboxSessionState",
]
