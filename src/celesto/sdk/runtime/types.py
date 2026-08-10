"""Types for managed agents: agents, runs, sessions, and end users.

Every response is a plain dictionary, so it prints and serializes like the
JSON it came from. These ``TypedDict`` definitions describe the keys you get
back and give editors autocompletion.

One value does not survive as JSON gave it: **money**. The API sends amounts as
fixed-scale decimal strings such as ``"0.000450"`` because a float cannot hold
them exactly. The SDK turns those into :class:`decimal.Decimal` so your
arithmetic stays exact, and never into ``float``.
"""

from decimal import Decimal
from typing import Any, Literal

from typing_extensions import NotRequired, TypedDict

# ============================================================================
# Agent configuration
# ============================================================================

ReasoningEffort = Literal["minimal", "low", "medium", "high"]
Verbosity = Literal["low", "medium", "high"]


class AgentConfig(TypedDict, total=False):
    """Generation settings an agent may carry.

    This is a closed set. Anything else is refused with 422
    ``config_key_not_allowed``, so the SDK checks it before the request leaves
    your machine.
    """

    temperature: float
    top_p: float
    max_tokens: int
    max_output_tokens: int
    frequency_penalty: float
    presence_penalty: float
    seed: int
    stop: str | list[str]
    reasoning_effort: ReasoningEffort
    verbosity: Verbosity
    max_turns: int


ALLOWED_CONFIG_KEYS: frozenset[str] = frozenset(AgentConfig.__annotations__)
"""Every key an agent ``config`` may contain."""


# ============================================================================
# Agents
# ============================================================================


class Agent(TypedDict):
    """A named, versioned agent definition."""

    id: str
    object: str
    name: str
    description: NotRequired[str | None]
    model: str
    instructions: NotRequired[str | None]
    config: NotRequired[AgentConfig | None]
    version: int
    current_version_id: str
    project_id: str
    organization_id: str
    status: str
    created_at: str
    updated_at: str


class AgentVersion(TypedDict):
    """One immutable snapshot of an agent definition."""

    id: str
    object: str
    agent_id: str
    version: int
    name: str
    description: NotRequired[str | None]
    model: str
    instructions: NotRequired[str | None]
    config: NotRequired[AgentConfig | None]
    created_at: str


class AgentPage(TypedDict):
    """One page of agents.

    There is no total count. ``has_more`` tells you whether to ask for the
    next page.
    """

    data: list[Agent]
    has_more: bool


class AgentVersionPage(TypedDict):
    """One page of agent versions."""

    data: list[AgentVersion]
    has_more: bool


class ArchivedAgent(TypedDict):
    """What archiving an agent returns."""

    id: str
    status: str


# ============================================================================
# Runs
# ============================================================================


class RunUsage(TypedDict):
    """Tokens and money spent by a run or a single generation.

    ``cost_usd`` is a :class:`~decimal.Decimal`.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal


class Run(TypedDict):
    """A settled run."""

    run_id: str
    object: str
    status: str
    error_code: NotRequired[str | None]
    error: NotRequired[str | None]
    output: NotRequired[str | None]
    usage: RunUsage
    agent_id: str
    agent_version_id: str
    session_id: str
    end_user_id: str
    turn_count: NotRequired[int | None]
    created_at: str
    started_at: NotRequired[str | None]
    ended_at: NotRequired[str | None]


class RunEventItem(TypedDict):
    """One stored event, as returned by the events endpoint."""

    seq: int
    event: str
    data: dict[str, Any]


class RunEventPage(TypedDict):
    """One page of stored run events.

    Page with ``after_seq`` set to the last ``seq`` you saw.
    """

    data: list[RunEventItem]
    events_version: str


# ============================================================================
# Sessions
# ============================================================================


class Session(TypedDict):
    """A conversation between one end user and one agent."""

    id: str
    object: str
    agent_id: NotRequired[str | None]
    end_user_id: str
    status: str
    message_count: int
    last_message_at: NotRequired[str | None]
    created_at: str


class SessionMessage(TypedDict):
    """One entry in a session transcript."""

    seq: int
    role: NotRequired[str | None]
    item: dict[str, Any]
    created_at: str


class SessionPage(TypedDict):
    """One page of sessions."""

    data: list[Session]
    has_more: bool


class SessionTranscript(TypedDict):
    """A session together with a page of its messages.

    Page backwards with ``before_seq`` set to the lowest ``seq`` you have.
    """

    session: Session
    messages: list[SessionMessage]


# ============================================================================
# End users
# ============================================================================


class EndUserBudget(TypedDict):
    """Spend and cap for one end user, in the current 30-day window.

    ``cap_usd``, ``spent_usd`` and ``remaining_usd`` are
    :class:`~decimal.Decimal`. A ``cap_usd`` of ``None`` means no cap.
    """

    cap_usd: NotRequired[Decimal | None]
    source: str
    window_start: str
    window_resets_at: str
    spent_usd: Decimal
    remaining_usd: NotRequired[Decimal | None]


class EndUser(TypedDict):
    """One of your users, addressed by your own identifier."""

    end_user_id: str
    object: str
    first_activity_at: str
    budget: EndUserBudget
    metadata: NotRequired[dict[str, Any] | None]
    created_at: str


class RuntimeSettings(TypedDict):
    """Organization-wide defaults for managed agents."""

    organization_id: str
    default_end_user_budget_usd: NotRequired[Decimal | None]


__all__ = [
    "ALLOWED_CONFIG_KEYS",
    "Agent",
    "AgentConfig",
    "AgentPage",
    "AgentVersion",
    "AgentVersionPage",
    "ArchivedAgent",
    "EndUser",
    "EndUserBudget",
    "ReasoningEffort",
    "Run",
    "RunEventItem",
    "RunEventPage",
    "RunUsage",
    "RuntimeSettings",
    "Session",
    "SessionMessage",
    "SessionPage",
    "SessionTranscript",
    "Verbosity",
]
