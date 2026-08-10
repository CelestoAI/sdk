"""Typed errors for managed agents.

The API answers a refused run with a machine-readable code so your code can
branch on *why* it was refused instead of matching on message text. Each code
gets its own exception class here, and every one of them is still a
``CelestoError``, so a single ``except CelestoError`` keeps working.

Two error body shapes exist in the wild::

    {"detail": "Agent not found"}
    {"detail": {"code": "budget_exceeded", "message": "..."}}

Both are handled; the code is only present in the second.
"""

from enum import Enum
from typing import Any

from ..exceptions import CelestoError, CelestoValidationError


class RunErrorCode(str, Enum):
    """Machine-readable reasons a run can be refused."""

    BUDGET_EXCEEDED = "budget_exceeded"
    SESSION_BUSY = "session_busy"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    AGENT_ARCHIVED = "agent_archived"
    PROVIDER_NOT_CONNECTED = "provider_not_connected"
    SESSION_AGENT_MISMATCH = "session_agent_mismatch"
    SESSION_END_USER_MISMATCH = "session_end_user_mismatch"
    MODEL_REQUIRES_OWN_KEY = "model_requires_own_key"
    CONFIG_KEY_NOT_ALLOWED = "config_key_not_allowed"


class ManagedAgentError(CelestoError):
    """A managed-agent request was refused with a known error code.

    Attributes:
        code: The API's error code, such as ``"budget_exceeded"``.
        status_code: The HTTP status that carried it.
        retry_after: Seconds to wait before retrying, when the API said so.
        retryable: True when retrying the identical request can succeed.
    """

    code: str | None = None
    retryable: bool = False

    def __init__(
        self,
        message: str,
        response: Any = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message, response)
        if code is not None:
            self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


class BudgetExceededError(ManagedAgentError):
    """402 — this end user's budget is spent for the current window.

    Raise the cap with ``client.end_users.update(end_user_id,
    budget_cap_usd=...)`` or wait for ``budget["window_resets_at"]``.
    """

    code = RunErrorCode.BUDGET_EXCEEDED.value


class SessionBusyError(ManagedAgentError):
    """409 — another run holds this session. Retryable.

    ``retry_after`` carries the API's Retry-After hint in seconds. Sessions
    run one at a time in v1, so the same request will succeed once the
    in-flight run settles.
    """

    code = RunErrorCode.SESSION_BUSY.value
    retryable = True


class IdempotencyConflictError(ManagedAgentError):
    """409 — this Idempotency-Key was already used with a different body.

    Use a fresh key for a different request, or replay the original body to
    get the stored run back.
    """

    code = RunErrorCode.IDEMPOTENCY_CONFLICT.value


class AgentArchivedError(ManagedAgentError):
    """409 — the agent is archived and cannot take new runs."""

    code = RunErrorCode.AGENT_ARCHIVED.value


class ProviderNotConnectedError(ManagedAgentError):
    """409 — no provider credential is connected for this agent's model."""

    code = RunErrorCode.PROVIDER_NOT_CONNECTED.value


class SessionAgentMismatchError(ManagedAgentError):
    """409 — that session belongs to a different agent."""

    code = RunErrorCode.SESSION_AGENT_MISMATCH.value


class SessionEndUserMismatchError(ManagedAgentError, CelestoValidationError):
    """422 — that session belongs to a different end user.

    Sessions are owned by one end user. Pass the session's own
    ``end_user_id``, or omit ``session_id`` to start a new session.
    """

    code = RunErrorCode.SESSION_END_USER_MISMATCH.value


class ModelRequiresOwnKeyError(ManagedAgentError, CelestoValidationError):
    """422 — this model can only run on your own provider key."""

    code = RunErrorCode.MODEL_REQUIRES_OWN_KEY.value


class ConfigKeyNotAllowedError(ManagedAgentError, CelestoValidationError):
    """422 — the agent config carried a key outside the allowed set.

    See ``celesto.sdk.runtime.ALLOWED_CONFIG_KEYS`` for what an agent config
    may contain.
    """

    code = RunErrorCode.CONFIG_KEY_NOT_ALLOWED.value


_ERROR_CLASSES: dict[str, type[ManagedAgentError]] = {
    RunErrorCode.BUDGET_EXCEEDED.value: BudgetExceededError,
    RunErrorCode.SESSION_BUSY.value: SessionBusyError,
    RunErrorCode.IDEMPOTENCY_CONFLICT.value: IdempotencyConflictError,
    RunErrorCode.AGENT_ARCHIVED.value: AgentArchivedError,
    RunErrorCode.PROVIDER_NOT_CONNECTED.value: ProviderNotConnectedError,
    RunErrorCode.SESSION_AGENT_MISMATCH.value: SessionAgentMismatchError,
    RunErrorCode.SESSION_END_USER_MISMATCH.value: SessionEndUserMismatchError,
    RunErrorCode.MODEL_REQUIRES_OWN_KEY.value: ModelRequiresOwnKeyError,
    RunErrorCode.CONFIG_KEY_NOT_ALLOWED.value: ConfigKeyNotAllowedError,
}

# Fallback for statuses that only managed agents use, when the body carries no
# recognizable code.
_STATUS_FALLBACK: dict[int, type[ManagedAgentError]] = {
    402: BudgetExceededError,
}


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        # Retry-After may also be an HTTP date. We do not guess at clock skew.
        return None


def error_for(
    *,
    status_code: int,
    body: Any,
    message: str,
    retry_after: str | None = None,
    response: Any = None,
) -> ManagedAgentError | None:
    """Build the typed error for a response, or None if the code is unknown."""
    code: str | None = None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):
            raw_code = detail.get("code")
            code = str(raw_code) if raw_code is not None else None
        if code is None and isinstance(body.get("code"), str):
            code = body["code"]

    error_class = _ERROR_CLASSES.get(code or "")
    if error_class is None:
        error_class = _STATUS_FALLBACK.get(status_code)
    if error_class is None:
        return None

    return error_class(
        message,
        response,
        code=code or error_class.code,
        status_code=status_code,
        retry_after=_retry_after_seconds(retry_after),
    )


__all__ = [
    "AgentArchivedError",
    "BudgetExceededError",
    "ConfigKeyNotAllowedError",
    "IdempotencyConflictError",
    "ManagedAgentError",
    "ModelRequiresOwnKeyError",
    "ProviderNotConnectedError",
    "RunErrorCode",
    "SessionAgentMismatchError",
    "SessionBusyError",
    "SessionEndUserMismatchError",
    "error_for",
]
