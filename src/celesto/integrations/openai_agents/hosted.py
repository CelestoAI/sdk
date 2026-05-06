"""Run OpenAI agents on hosted Celesto computers.

Use this module when you want Celesto to create the computer for an OpenAI
``SandboxAgent``. The agent can run commands and write files in that computer.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Any, Literal

from celesto.integrations.openai_agents.common import (
    BaseSandboxClient,
    BaseSandboxClientOptions,
    CommandBackedSession,
    Manifest,
    SandboxSession,
    SandboxSessionState,
    SnapshotBase,
    SnapshotSpec,
    resolve_snapshot,
    timeout_seconds,
)
from celesto.sdk.client import Celesto


class CelestoSandboxClientOptions(BaseSandboxClientOptions):
    """Settings for running a ``SandboxAgent`` on a Celesto computer."""

    type: Literal["celesto"] = "celesto"
    computer_id: str | None = None
    cpus: int = 1
    memory: int = 1024
    image: str = "ubuntu-desktop-24.04"
    delete_on_close: bool | None = None


class CelestoSandboxSessionState(SandboxSessionState):
    """Information needed to reconnect to a Celesto computer later."""

    type: Literal["celesto"] = "celesto"
    computer_id: str | None = None
    cpus: int = 1
    memory: int = 1024
    image: str = "ubuntu-desktop-24.04"
    delete_on_close: bool = True


class CelestoSandboxSession(CommandBackedSession):
    """A running OpenAI agent workspace on a Celesto computer."""

    state: CelestoSandboxSessionState

    def __init__(self, *, state: CelestoSandboxSessionState, client: Celesto) -> None:
        self.state = state
        self._client = client
        self._running = False
        self._command_lock = asyncio.Lock()

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
            raise RuntimeError(
                "No Celesto computer is ready yet. Start the session with "
                "`async with session:` before running commands."
            )
        async with self._command_lock:
            return await asyncio.to_thread(
                self._client.computers.exec,
                self.state.computer_id,
                command,
                timeout=timeout_seconds(timeout),
            )

    async def _delete_backend(self) -> None:
        if self.state.computer_id is None:
            return
        if self.state.delete_on_close:
            with suppress(Exception):
                await asyncio.to_thread(self._client.computers.delete, self.state.computer_id)
        self._running = False


class CelestoSandboxClient(BaseSandboxClient[CelestoSandboxClientOptions | None]):
    """Create and manage Celesto computers for OpenAI agents."""

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
            raise TypeError(
                "Wrong session type. Use CelestoSandboxClient with CelestoSandboxSession."
            )
        await inner._delete_backend()
        return session

    async def resume(self, state: SandboxSessionState) -> SandboxSession:
        if not isinstance(state, CelestoSandboxSessionState):
            raise TypeError(
                "Wrong saved session type. Use CelestoSandboxClient with "
                "CelestoSandboxSessionState."
            )
        inner = CelestoSandboxSession.from_state(state, client=self._client)
        inner._set_start_state_preserved(True)
        return self._wrap_session(inner)

    def deserialize_session_state(self, payload: dict[str, object]) -> SandboxSessionState:
        return CelestoSandboxSessionState.model_validate(payload)


__all__ = [
    "CelestoSandboxClient",
    "CelestoSandboxClientOptions",
    "CelestoSandboxSession",
    "CelestoSandboxSessionState",
]
