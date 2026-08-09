"""The run event stream.

A run is an append-only log; streaming is just tailing it. The wire format is
Server-Sent Events, and the event names are a versioned, closed set:

``run.started``, ``message.delta``, ``message.completed``, ``tool.call``,
``tool.result``, ``usage``, ``run.completed``, ``run.failed``.

**Unknown event names are ignored.** That is the forward-compatibility
contract: the server may add an event tomorrow and today's SDK must not break
on it. :func:`to_run_event` returns ``None`` for anything it does not know, and
:func:`iter_run_events` drops those frames.

Every frame except ``message.delta`` carries an ``id:`` — the event's sequence
number. Deltas are not persisted, so they are not positions you can resume
from, and their ``seq`` is ``None``.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .money import to_decimal

EVENTS_VERSION = "1"
"""The event contract this SDK was written against (``X-Celesto-Events-Version``)."""

EVENTS_VERSION_HEADER = "X-Celesto-Events-Version"

RUN_STARTED = "run.started"
MESSAGE_DELTA = "message.delta"
MESSAGE_COMPLETED = "message.completed"
TOOL_CALL = "tool.call"
TOOL_RESULT = "tool.result"
USAGE = "usage"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"

KNOWN_EVENTS: frozenset[str] = frozenset(
    {
        RUN_STARTED,
        MESSAGE_DELTA,
        MESSAGE_COMPLETED,
        TOOL_CALL,
        TOOL_RESULT,
        USAGE,
        RUN_COMPLETED,
        RUN_FAILED,
    }
)

TERMINAL_EVENTS: frozenset[str] = frozenset({RUN_COMPLETED, RUN_FAILED})


@dataclass(frozen=True)
class SSEFrame:
    """One raw Server-Sent Events frame, before it is understood."""

    event: str | None = None
    data: str = ""
    id: str | None = None


@dataclass(frozen=True)
class RunEvent:
    """One thing that happened during a run.

    Attributes:
        name: The event name, such as ``"message.delta"``.
        data: The event body. Money inside it is already a
            :class:`~decimal.Decimal`.
        seq: The event's position in the run's log, or ``None`` for
            ``message.delta`` frames, which are not stored.
    """

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    seq: int | None = None

    @property
    def text(self) -> str:
        """The text this event carries, or ``""``.

        Set on ``message.delta`` (the new fragment), ``message.completed``
        (the whole message), and ``run.completed`` (the final output).
        """
        value = self.data.get("text")
        if value is None and self.name == RUN_COMPLETED:
            value = self.data.get("output")
        return value if isinstance(value, str) else ""

    @property
    def is_terminal(self) -> bool:
        """True for ``run.completed`` and ``run.failed``: the run is settled."""
        return self.name in TERMINAL_EVENTS

    @property
    def cost_usd(self) -> Decimal | None:
        """What this event cost, when it says."""
        if "cost_usd" in self.data:
            return to_decimal(self.data.get("cost_usd"))
        usage = self.data.get("usage")
        if isinstance(usage, dict) and "cost_usd" in usage:
            return to_decimal(usage.get("cost_usd"))
        return None


def _coerce_money(data: Any) -> Any:
    """Turn every ``cost_usd`` in an event body into a Decimal, in place."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "cost_usd":
                data[key] = to_decimal(value)
            else:
                _coerce_money(value)
    elif isinstance(data, list):
        for item in data:
            _coerce_money(item)
    return data


def to_run_event(frame: SSEFrame) -> RunEvent | None:
    """Turn one raw frame into a run event, or ``None`` to ignore it.

    Returns ``None`` for comments, keep-alives, and — deliberately — event
    names this SDK does not know. Do not change that: an older client must
    survive a newer server.
    """
    name = frame.event
    if name is None or name not in KNOWN_EVENTS:
        return None

    try:
        data = json.loads(frame.data) if frame.data else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    seq: int | None = None
    if frame.id is not None:
        try:
            seq = int(frame.id)
        except ValueError:
            seq = None

    return RunEvent(name=name, data=_coerce_money(data), seq=seq)


def iter_sse_frames(lines: Iterable[str]) -> Iterator[SSEFrame]:
    """Parse SSE lines into frames.

    Accepts the line stream from an HTTP response, with or without trailing
    newlines. A blank line dispatches the frame it just finished.
    """
    event: str | None = None
    data_lines: list[str] = []
    event_id: str | None = None
    seen_field = False

    for raw_line in lines:
        line = raw_line.rstrip("\n").rstrip("\r")

        if line == "":
            if seen_field:
                yield SSEFrame(event=event, data="\n".join(data_lines), id=event_id)
            event, data_lines, event_id, seen_field = None, [], None, False
            continue

        if line.startswith(":"):
            # A comment. Servers send these as keep-alives.
            continue

        field_name, _, value = line.partition(":")
        value = value.removeprefix(" ")

        if field_name == "event":
            event, seen_field = value, True
        elif field_name == "data":
            data_lines.append(value)
            seen_field = True
        elif field_name == "id":
            event_id, seen_field = value, True
        # "retry" and unknown fields are ignored, per the SSE spec.

    if seen_field:
        yield SSEFrame(event=event, data="\n".join(data_lines), id=event_id)


def iter_run_events(lines: Iterable[str]) -> Iterator[RunEvent]:
    """Parse SSE lines straight into run events, ignoring unknown ones."""
    for frame in iter_sse_frames(lines):
        event = to_run_event(frame)
        if event is not None:
            yield event


__all__ = [
    "EVENTS_VERSION",
    "EVENTS_VERSION_HEADER",
    "KNOWN_EVENTS",
    "MESSAGE_COMPLETED",
    "MESSAGE_DELTA",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_STARTED",
    "TERMINAL_EVENTS",
    "TOOL_CALL",
    "TOOL_RESULT",
    "USAGE",
    "RunEvent",
    "SSEFrame",
    "iter_run_events",
    "iter_sse_frames",
    "to_run_event",
]
