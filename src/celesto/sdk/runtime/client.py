"""Managed agents: run your agents for your end users.

You define an agent once — a name, a model, instructions — and then run it on
behalf of *your* users. Every run names the end user it acts for, using your
own identifier for them (``"usr_8837"``, ``"alice@acme.com"``). Celesto keeps
that user's spend, budget, and transcript together, so "what has this user
spent this month?" is one call.

Five namespaces hang off the client, named the same in every Celesto SDK:

- ``agents`` — create, update (which cuts a new version), archive, roll back.
- ``runs`` — run an agent, stream what it does, read a settled run's events.
- ``sessions`` — the conversations an end user has had.
- ``end_users`` — budget, spend, and metadata for one of your users.
- ``settings`` — organization-wide defaults, such as the starting budget.
"""

import random
import time
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

import httpx
from typing_extensions import Self

from ..base import _BaseClient, _BaseConnection
from ..exceptions import CelestoNetworkError
from .errors import ConfigKeyNotAllowedError, SessionBusyError, error_for
from .events import RunEvent, iter_run_events
from .money import MoneyInput, parse_money_fields, to_money_string
from .types import (
    ALLOWED_CONFIG_KEYS,
    Agent,
    AgentConfig,
    AgentPage,
    AgentVersion,
    AgentVersionPage,
    ArchivedAgent,
    EndUser,
    Run,
    RunEventItem,
    RunEventPage,
    RuntimeSettings,
    Session,
    SessionMessage,
    SessionPage,
    SessionTranscript,
)

DEFAULT_RUN_TIMEOUT_SECONDS = 900
"""How long to wait for a run before giving up. Runs can be slow; agents think."""

_DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
_MAX_RETRY_BACKOFF_SECONDS = 30.0


def _busy_backoff(busy: SessionBusyError, attempt: int) -> float:
    """How long to wait before knocking on a busy session again.

    ``retry_after`` wins whenever the server sent one, including ``0`` — the
    server saying "come straight back" is an instruction, and reading 0 as
    "unset" turned it into a full second of nothing. (``or`` treats 0 as
    missing; this does not.)

    Without a hint, back off exponentially with jitter. A flat one-second wait
    means every caller queued on the same session wakes together and knocks in
    step, and the run holding the claim can last minutes — so the retries least
    likely to succeed were also the ones repeated most often.
    """
    if busy.retry_after is not None:
        return max(0.0, float(busy.retry_after))
    ceiling = min(
        _DEFAULT_RETRY_BACKOFF_SECONDS * (2**attempt), _MAX_RETRY_BACKOFF_SECONDS
    )
    # Full jitter: uniform over [0, ceiling] rather than ceiling ± a little, so
    # a thundering herd spreads out instead of shifting together.
    return random.uniform(0.0, ceiling)


class _Unset:
    """Marks an argument you did not pass, which is not the same as ``None``."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()
"""Sentinel for "leave this field alone" on the update calls.

Passing ``None`` clears a value; passing nothing leaves it as it is.
"""


def _validate_config(
    config: AgentConfig | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Refuse a config the API would refuse, before the request is sent."""
    if config is None:
        return None
    unknown = sorted(set(config) - ALLOWED_CONFIG_KEYS)
    if unknown:
        allowed = ", ".join(sorted(ALLOWED_CONFIG_KEYS))
        raise ConfigKeyNotAllowedError(
            f"Agent config does not accept {', '.join(unknown)}. "
            f"It accepts only: {allowed}."
        )
    return dict(config)


class _RuntimeBaseClient(_BaseClient):
    """Shared behavior for the managed-agent namespaces.

    Adds two things to the standard client: money is parsed into ``Decimal``
    on the way out, and refusals with a known error code raise their own
    exception type.
    """

    def _json_request(self, method, path, **kwargs) -> Any:
        return parse_money_fields(self._request(method, path, **kwargs))

    def _handle_response(self, response: httpx.Response) -> Any:
        status = response.status_code
        if status in (200, 201, 204):
            return super()._handle_response(response)

        body: Any = None
        try:
            body = response.json()
        except ValueError:
            body = None

        typed = error_for(
            status_code=status,
            body=body,
            message=self._extract_error_message(response),
            retry_after=response.headers.get("Retry-After"),
            response=response,
        )
        if typed is not None:
            raise typed

        return super()._handle_response(response)


class Agents(_RuntimeBaseClient):
    """Create and version the agents your end users run.

    An agent is a named pointer at an immutable definition. Every update cuts
    a new version and moves the pointer; runs pin the version they started
    with, so a change never rewrites history. Rolling back moves the pointer
    and cuts nothing.

    Example:
        agent = client.agents.create(
            name="support-bot",
            model="openai/gpt-5.4-mini",
            instructions="Answer order questions in one short paragraph.",
        )
    """

    def create(
        self,
        *,
        name: str,
        model: str,
        instructions: str | None = None,
        description: str | None = None,
        config: AgentConfig | None = None,
        project_id: str | None = None,
    ) -> Agent:
        """Create an agent.

        Args:
            name: Display name, 1-255 characters.
            model: Model to run, such as ``"openai/gpt-5.4-mini"``. Pinned per version.
            instructions: The system prompt.
            description: Free text for your own dashboard, up to 1000 characters.
            config: Generation settings. Only the keys in
                :data:`~celesto.sdk.runtime.ALLOWED_CONFIG_KEYS` are accepted.
            project_id: Project to scope the agent to. Defaults to your
                organization's default project.

        Returns:
            The new agent, at version 1.
        """
        payload: dict[str, Any] = {"name": name, "model": model}
        if instructions is not None:
            payload["instructions"] = instructions
        if description is not None:
            payload["description"] = description
        if config is not None:
            payload["config"] = _validate_config(config)
        if project_id is not None:
            payload["project_id"] = project_id
        return self._json_request("POST", "/agents", json_body=payload)

    def list(
        self,
        *,
        project_id: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> AgentPage:
        """List one page of agents.

        There is no total count. ``has_more`` says whether another page
        exists; :meth:`iter_all` walks them for you.

        Args:
            project_id: Only agents in this project.
            include_archived: Include archived agents too.
            limit: Page size, 1-100.
            offset: How many agents to skip.
        """
        params: dict[str, Any] = {
            "include_archived": include_archived,
            "limit": limit,
            "offset": offset,
        }
        if project_id is not None:
            params["project_id"] = project_id
        return self._json_request("GET", "/agents", params=params)

    def iter_all(
        self,
        *,
        project_id: str | None = None,
        include_archived: bool = False,
        page_size: int = 50,
    ) -> Iterator[Agent]:
        """Yield every agent, fetching pages as you go."""
        offset = 0
        while True:
            page = self.list(
                project_id=project_id,
                include_archived=include_archived,
                limit=page_size,
                offset=offset,
            )
            items: list[Agent] = page.get("data") or []
            yield from items
            if not items or not page.get("has_more"):
                return
            offset += len(items)

    def get(self, agent_id: str) -> Agent:
        """Get an agent, at its current version."""
        return self._json_request("GET", f"/agents/{agent_id}")

    def update(
        self,
        agent_id: str,
        *,
        name: str,
        model: str,
        instructions: str | None = None,
        description: str | None = None,
        config: AgentConfig | None = None,
    ) -> Agent:
        """Replace an agent's definition, which cuts a new version.

        This is a full replacement, not a patch: whatever you leave out is
        cleared. Read the agent first if you only mean to change one field.

        Returns:
            The agent, now pointing at the new version.
        """
        payload: dict[str, Any] = {"name": name, "model": model}
        if instructions is not None:
            payload["instructions"] = instructions
        if description is not None:
            payload["description"] = description
        if config is not None:
            payload["config"] = _validate_config(config)
        return self._json_request("PUT", f"/agents/{agent_id}", json_body=payload)

    def archive(self, agent_id: str) -> ArchivedAgent:
        """Archive an agent. Archived agents refuse new runs.

        Past runs, versions, and transcripts stay readable.
        """
        return self._json_request("DELETE", f"/agents/{agent_id}")

    def list_versions(
        self, agent_id: str, *, limit: int = 50, offset: int = 0
    ) -> AgentVersionPage:
        """List one page of an agent's versions, newest first."""
        return self._json_request(
            "GET",
            f"/agents/{agent_id}/versions",
            params={"limit": limit, "offset": offset},
        )

    def iter_versions(
        self, agent_id: str, *, page_size: int = 50
    ) -> Iterator[AgentVersion]:
        """Yield every version of an agent, fetching pages as you go."""
        offset = 0
        while True:
            page = self.list_versions(agent_id, limit=page_size, offset=offset)
            items: list[AgentVersion] = page.get("data") or []
            yield from items
            if not items or not page.get("has_more"):
                return
            offset += len(items)

    def get_version(self, agent_id: str, version_number: int) -> AgentVersion:
        """Get one version of an agent by its number."""
        return self._json_request(
            "GET", f"/agents/{agent_id}/versions/{version_number}"
        )

    def activate_version(self, agent_id: str, version_number: int) -> Agent:
        """Roll back to an earlier version.

        This moves the agent's pointer; it does not cut a new version and
        nothing is lost.
        """
        return self._json_request(
            "POST", f"/agents/{agent_id}/versions/{version_number}/activate"
        )


class Runs(_RuntimeBaseClient):
    """Run an agent for one of your end users, and read what happened.

    Two ways to run, so the return type never depends on an argument:

    - :meth:`create` waits and hands you the settled run.
    - :meth:`stream` hands you events as they happen.

    Example:
        run = client.runs.create(agent["id"], input="Where is my order?",
                                 end_user_id="usr_8837")
        print(run["output"], run["usage"]["cost_usd"])
    """

    def _run_body(
        self,
        *,
        input: str,
        end_user_id: str,
        session_id: str | None,
        max_turns: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "input": input,
            "end_user_id": end_user_id,
            "stream": stream,
        }
        if session_id is not None:
            body["session_id"] = session_id
        if max_turns is not None:
            body["max_turns"] = max_turns
        return body

    @staticmethod
    def _headers(idempotency_key: str | None) -> dict[str, str] | None:
        return {"Idempotency-Key": idempotency_key} if idempotency_key else None

    @staticmethod
    def _resolve_idempotency_key(
        idempotency_key: str | None, max_retries: int
    ) -> str | None:
        """Retrying without a key can charge twice, so make one when retrying."""
        if idempotency_key or max_retries <= 0:
            return idempotency_key
        return uuid.uuid4().hex

    def create(
        self,
        agent_id: str,
        *,
        input: str,
        end_user_id: str,
        session_id: str | None = None,
        max_turns: int | None = None,
        idempotency_key: str | None = None,
        max_retries: int = 0,
        timeout: float | None = None,
    ) -> Run:
        """Run an agent and wait for the answer.

        Args:
            agent_id: The agent to run.
            input: What the end user said.
            end_user_id: Your own identifier for the person this run acts for.
                Celesto stores it as you send it and never parses it.
            session_id: Continue an existing conversation. Omit to start a new
                one; the session is created for you.
            max_turns: Stop the agent after this many turns, 1-100.
            idempotency_key: Send the same key to retry safely. A replay
                returns the stored run instead of running the agent again.
            max_retries: How many times to retry when the session is busy.
                Sessions run one at a time, so a second run on the same
                session is refused until the first settles. An idempotency
                key is generated for you when you ask for retries.
            timeout: Seconds to wait for the run. Defaults to 15 minutes.

        Returns:
            The settled run, including ``output`` and ``usage``.

        Raises:
            BudgetExceededError: The end user has spent their budget.
            SessionBusyError: Another run holds the session, after retries.
            AgentArchivedError: The agent no longer takes runs.
        """
        key = self._resolve_idempotency_key(idempotency_key, max_retries)
        body = self._run_body(
            input=input,
            end_user_id=end_user_id,
            session_id=session_id,
            max_turns=max_turns,
            stream=False,
        )
        read_timeout = self._timeout_with_read(timeout or DEFAULT_RUN_TIMEOUT_SECONDS)

        for attempt in range(max_retries + 1):
            try:
                return self._json_request(
                    "POST",
                    f"/agents/{agent_id}/runs",
                    json_body=body,
                    headers=self._headers(key),
                    timeout=read_timeout,
                )
            except SessionBusyError as busy:
                if attempt >= max_retries:
                    raise
                time.sleep(_busy_backoff(busy, attempt))

        raise AssertionError("unreachable")  # pragma: no cover

    def stream(
        self,
        agent_id: str,
        *,
        input: str,
        end_user_id: str,
        session_id: str | None = None,
        max_turns: int | None = None,
        idempotency_key: str | None = None,
        max_retries: int = 0,
        timeout: float | None = None,
    ) -> Iterator[RunEvent]:
        """Run an agent and watch it work.

        Yields :class:`~celesto.sdk.runtime.RunEvent` objects as the run
        happens: text as it is generated, each tool call and its result, what
        each generation cost, and finally ``run.completed`` or ``run.failed``.

        Event names this SDK does not know are ignored, so a newer server
        cannot break an older client.

        A failed run arrives as a ``run.failed`` event, not an exception —
        including a run stopped mid-stream because the end user ran out of
        budget. Exceptions are for runs that never started.

        Args:
            agent_id: The agent to run.
            input: What the end user said.
            end_user_id: Your own identifier for the person this run acts for.
            session_id: Continue an existing conversation.
            max_turns: Stop the agent after this many turns, 1-100.
            idempotency_key: Send the same key to retry safely. A replay does
                not include ``message.delta`` events: partial text is never
                stored, so there is nothing to replay.
            max_retries: How many times to retry when the session is busy.
            timeout: Seconds to wait for the run. Defaults to 15 minutes.

        Example:
            for event in client.runs.stream(agent_id, input="Hi",
                                            end_user_id="usr_8837"):
                if event.name == "message.delta":
                    print(event.text, end="", flush=True)
        """
        key = self._resolve_idempotency_key(idempotency_key, max_retries)
        body = self._run_body(
            input=input,
            end_user_id=end_user_id,
            session_id=session_id,
            max_turns=max_turns,
            stream=True,
        )
        read_timeout = self._timeout_with_read(timeout or DEFAULT_RUN_TIMEOUT_SECONDS)
        url = f"{self.base_url}/agents/{agent_id}/runs"
        headers = {"Accept": "text/event-stream"}
        if key:
            headers["Idempotency-Key"] = key

        for attempt in range(max_retries + 1):
            try:
                yield from self._iter_events(url, body, headers, read_timeout)
                return
            except SessionBusyError as busy:
                if attempt >= max_retries:
                    raise
                time.sleep(_busy_backoff(busy, attempt))

    def _iter_events(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        timeout: httpx.Timeout,
    ) -> Iterator[RunEvent]:
        try:
            with self.session.stream(
                "POST", url, json=body, headers=headers, timeout=timeout
            ) as response:
                if response.status_code not in (200, 201):
                    response.read()
                    self._handle_response(response)
                yield from iter_run_events(response.iter_lines())
        except httpx.ConnectError as e:
            raise CelestoNetworkError(f"Failed to connect to Celesto API: {e}") from e
        except httpx.TimeoutException as e:
            raise CelestoNetworkError(f"Request to Celesto API timed out: {e}") from e
        except httpx.HTTPError as e:
            raise CelestoNetworkError(
                f"Network error while contacting Celesto API: {e}"
            ) from e

    def get(self, run_id: str) -> Run:
        """Get a run by id, settled or not."""
        return self._json_request("GET", f"/runs/{run_id}")

    def list_events(
        self, run_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> RunEventPage:
        """Read one page of a run's stored events.

        This is the same event contract as :meth:`stream`, read back after the
        fact, minus ``message.delta`` — partial text is never stored.

        Args:
            run_id: The run to read.
            after_seq: Return events after this sequence number. Pass the last
                ``seq`` you saw to continue.
            limit: Page size, 1-500.
        """
        return self._json_request(
            "GET",
            f"/runs/{run_id}/events",
            params={"after_seq": after_seq, "limit": limit},
        )

    def iter_events(
        self, run_id: str, *, after_seq: int = 0, page_size: int = 100
    ) -> Iterator[RunEventItem]:
        """Yield every stored event of a run, in order, fetching pages as you go."""
        cursor = after_seq
        while True:
            page = self.list_events(run_id, after_seq=cursor, limit=page_size)
            items: list[RunEventItem] = page.get("data") or []
            yield from items
            # This endpoint reports no `has_more`; a short page is the end.
            if len(items) < page_size:
                return
            cursor = items[-1]["seq"]


class Sessions(_RuntimeBaseClient):
    """The conversations your end users have had.

    A session holds one end user's transcript with one agent. Runs on the same
    session share history; runs without a session get a fresh one.
    """

    def list(
        self, *, end_user_id: str, limit: int = 50, offset: int = 0
    ) -> SessionPage:
        """List one page of an end user's sessions.

        Args:
            end_user_id: Your own identifier for the end user.
            limit: Page size, 1-100.
            offset: How many sessions to skip.
        """
        return self._json_request(
            "GET",
            "/sessions",
            params={"end_user_id": end_user_id, "limit": limit, "offset": offset},
        )

    def iter_all(self, *, end_user_id: str, page_size: int = 50) -> Iterator[Session]:
        """Yield every session for an end user, fetching pages as you go."""
        offset = 0
        while True:
            page = self.list(end_user_id=end_user_id, limit=page_size, offset=offset)
            items: list[Session] = page.get("data") or []
            yield from items
            if not items or not page.get("has_more"):
                return
            offset += len(items)

    def get(
        self, session_id: str, *, limit: int = 50, before_seq: int | None = None
    ) -> SessionTranscript:
        """Get a session and a page of its transcript.

        The transcript pages backwards: the most recent messages come first,
        and ``before_seq`` asks for what came before a message you already
        have.

        Args:
            session_id: The session to read.
            limit: How many messages to return, 1-200.
            before_seq: Return messages before this sequence number.
        """
        params: dict[str, Any] = {"limit": limit}
        if before_seq is not None:
            params["before_seq"] = before_seq
        return self._json_request("GET", f"/sessions/{session_id}", params=params)

    def iter_messages(
        self, session_id: str, *, page_size: int = 50, before_seq: int | None = None
    ) -> Iterator[SessionMessage]:
        """Yield a session's messages newest first, fetching pages as you go."""
        cursor = before_seq
        while True:
            transcript = self.get(session_id, limit=page_size, before_seq=cursor)
            messages: list[SessionMessage] = transcript.get("messages") or []
            if not messages:
                return
            yield from sorted(messages, key=lambda m: m["seq"], reverse=True)
            if len(messages) < page_size:
                return
            cursor = min(message["seq"] for message in messages)


class EndUsers(_RuntimeBaseClient):
    """Your users: what they have spent, and what they are allowed to spend.

    An end user is addressed by *your* identifier for them. You never store a
    Celesto id, and the record is created the first time you run an agent for
    them.

    Example:
        user = client.end_users.get("usr_8837")
        print(user["budget"]["spent_usd"], "of", user["budget"]["cap_usd"])
    """

    def get(self, end_user_id: str) -> EndUser:
        """Get an end user's budget and activity.

        Money comes back as :class:`~decimal.Decimal`.
        """
        return self._json_request("GET", f"/end_users/{end_user_id}")

    def update(
        self,
        end_user_id: str,
        *,
        budget_cap_usd: MoneyInput | _Unset | None = UNSET,
        metadata: dict[str, Any] | _Unset | None = UNSET,
    ) -> EndUser:
        """Set an end user's budget override or metadata.

        Creates the end user if they have not run anything yet.

        Fields you do not pass are left alone. Passing ``None`` clears the
        field: ``budget_cap_usd=None`` drops back to your organization's
        default budget.

        Args:
            end_user_id: Your own identifier for the end user.
            budget_cap_usd: Spend cap for the rolling 30-day window. Pass a
                ``Decimal`` or a string to stay exact.
            metadata: Free-form JSON of your own.
        """
        payload: dict[str, Any] = {}
        if not isinstance(budget_cap_usd, _Unset):
            payload["budget_cap_usd"] = (
                None if budget_cap_usd is None else to_money_string(budget_cap_usd)
            )
        if not isinstance(metadata, _Unset):
            payload["metadata"] = metadata
        return self._json_request("PUT", f"/end_users/{end_user_id}", json_body=payload)

    def clear_budget(self, end_user_id: str) -> EndUser:
        """Drop an end user's override, back to the organization default."""
        return self.update(end_user_id, budget_cap_usd=None)


class Settings(_RuntimeBaseClient):
    """Organization-wide defaults for managed agents."""

    def get(self) -> RuntimeSettings:
        """Read the default budget every end user starts with."""
        return self._json_request("GET", "/runtime/settings")

    def update(
        self, *, default_end_user_budget_usd: MoneyInput | _Unset | None = UNSET
    ) -> RuntimeSettings:
        """Set the default budget every end user starts with.

        Pass ``None`` to remove the default, which leaves end users uncapped
        unless they have their own override.
        """
        payload: dict[str, Any] = {}
        if not isinstance(default_end_user_budget_usd, _Unset):
            payload["default_end_user_budget_usd"] = (
                None
                if default_end_user_budget_usd is None
                else to_money_string(default_end_user_budget_usd)
            )
        return self._json_request("PUT", "/runtime/settings", json_body=payload)


class ManagedAgentsClient(_BaseConnection):
    """Run your agents for your end users.

    Reads ``CELESTO_API_KEY`` from the environment when you do not pass a key.
    Use it as a context manager, or call ``close()`` when you are done.

    Args:
        api_key: Your Celesto API key.
        base_url: Custom API base URL, for testing.
        organization_id: Organization to act as. An organization-scoped API
            key already names one, so this is rarely needed.

    Example:
        from celesto import ManagedAgentsClient

        celesto = ManagedAgentsClient()
        agent = celesto.agents.create(name="support-bot", model="openai/gpt-5.4-mini")
        run = celesto.runs.create(agent["id"], input="Where is my order?",
                                  end_user_id="usr_8837")
        print(run["output"])
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        organization_id: str | None = None,
    ):
        super().__init__(api_key, base_url, organization_id)
        self.agents = Agents(self)
        self.runs = Runs(self)
        self.sessions = Sessions(self)
        self.end_users = EndUsers(self)
        self.settings = Settings(self)

    def __enter__(self) -> Self:
        return self


__all__ = [
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "UNSET",
    "Agents",
    "EndUsers",
    "ManagedAgentsClient",
    "Runs",
    "Sessions",
    "Settings",
]
