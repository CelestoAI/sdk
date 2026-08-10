from decimal import Decimal

import httpx
import pytest

import celesto
from celesto import ManagedAgentsClient
from celesto.sdk.client import _CelestoClient
from celesto.sdk.runtime import (
    ALLOWED_CONFIG_KEYS,
    BudgetExceededError,
    ConfigKeyNotAllowedError,
    ManagedAgentError,
    ModelRequiresOwnKeyError,
    RunEvent,
    SessionBusyError,
    iter_run_events,
    iter_sse_frames,
    to_money_string,
)

BASE_URL = "https://api.example.test/v1"


class DummySession:
    """Records calls and replays queued responses, like the computers tests."""

    def __init__(self, *, status_code: int = 200, payload=None, responses=None):
        self.calls = []
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.responses = list(responses or [])
        self.timeout = httpx.Timeout(connect=10, read=120, write=10, pool=10)

    def _next(self):
        if self.responses:
            queued = self.responses.pop(0)
            return (
                queued.get("status_code", 200),
                queued.get("payload", {}),
                queued.get("headers", {}),
            )
        return self.status_code, self.payload, {}

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        status_code, payload, headers = self._next()
        return httpx.Response(
            status_code,
            json=payload,
            headers=headers,
            request=httpx.Request(method, url),
        )

    def close(self):
        pass


def make_client(session: DummySession) -> ManagedAgentsClient:
    client = ManagedAgentsClient("test-key", base_url=BASE_URL)
    client.session = session
    return client


def sse_client(handler) -> ManagedAgentsClient:
    """A client whose transport is a real httpx stack over a fake network."""
    client = ManagedAgentsClient("test-key", base_url=BASE_URL)
    client.session = httpx.Client(transport=httpx.MockTransport(handler))
    return client


AGENT_PAYLOAD = {
    "id": "agt_1",
    "object": "agent",
    "name": "support-bot",
    "model": "openai/gpt-5.4-mini",
    "instructions": "Be brief.",
    "config": {"temperature": 0.2},
    "version": 1,
    "current_version_id": "agv_1",
    "project_id": "prj_1",
    "organization_id": "org_1",
    "status": "active",
    "created_at": "2026-08-09T00:00:00Z",
    "updated_at": "2026-08-09T00:00:00Z",
}

RUN_PAYLOAD = {
    "run_id": "run_1",
    "object": "run",
    "status": "completed",
    "output": "Your order ships tomorrow.",
    "usage": {
        "input_tokens": 120,
        "output_tokens": 32,
        "total_tokens": 152,
        "cost_usd": "0.000450",
    },
    "agent_id": "agt_1",
    "agent_version_id": "agv_1",
    "session_id": "ses_1",
    "end_user_id": "usr_8837",
    "turn_count": 1,
    "created_at": "2026-08-09T00:00:00Z",
}


# ============================================================================
# Wiring
# ============================================================================


def test_managed_agent_namespaces_hang_off_both_clients():
    assert celesto.ManagedAgentsClient is ManagedAgentsClient

    public = ManagedAgentsClient("test-key", base_url=BASE_URL)
    internal = _CelestoClient("test-key", base_url=BASE_URL)
    for client in (public, internal):
        assert hasattr(client, "agents")
        assert hasattr(client, "runs")
        assert hasattr(client, "sessions")
        assert hasattr(client, "end_users")
        assert hasattr(client, "settings")


def test_namespace_names_match_the_typescript_sdk():
    """Five namespaces, one name each, across both SDKs. This one was
    ``runtime`` in Python and ``settings`` in TypeScript, so anything written
    against one SDK mistranslated against the other — and
    ``runtime.get_settings()`` stuttered besides."""
    client = ManagedAgentsClient("test-key", base_url=BASE_URL)
    # end_users/endUsers differ only by each language's casing convention.
    assert {"agents", "runs", "sessions", "end_users", "settings"} <= set(vars(client))
    assert not hasattr(client, "runtime")
    assert callable(client.settings.get)
    assert callable(client.settings.update)


def test_organization_id_is_sent_as_a_header_when_given():
    client = ManagedAgentsClient(
        "test-key", base_url=BASE_URL, organization_id="org_42"
    )
    assert client.session.headers["X-Current-Organization"] == "org_42"


# ============================================================================
# Agents and the config allowlist
# ============================================================================


def test_create_agent_posts_the_definition_and_returns_it():
    session = DummySession(status_code=201, payload=AGENT_PAYLOAD)
    client = make_client(session)

    agent = client.agents.create(
        name="support-bot",
        model="openai/gpt-5.4-mini",
        instructions="Be brief.",
        config={"temperature": 0.2, "max_turns": 4},
    )

    assert agent["id"] == "agt_1"
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"] == f"{BASE_URL}/agents"
    assert session.calls[0]["json"] == {
        "name": "support-bot",
        "model": "openai/gpt-5.4-mini",
        "instructions": "Be brief.",
        "config": {"temperature": 0.2, "max_turns": 4},
    }


def test_agent_config_outside_the_allowlist_is_refused_before_sending():
    session = DummySession(status_code=201, payload=AGENT_PAYLOAD)
    client = make_client(session)

    with pytest.raises(ConfigKeyNotAllowedError) as excinfo:
        client.agents.create(
            name="support-bot", model="openai/gpt-5.4-mini", config={"tempurature": 0.2}
        )

    assert "tempurature" in str(excinfo.value)
    assert session.calls == []


def test_allowed_config_keys_match_the_documented_set():
    assert ALLOWED_CONFIG_KEYS == {
        "temperature",
        "top_p",
        "max_tokens",
        "max_output_tokens",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "stop",
        "reasoning_effort",
        "verbosity",
        "max_turns",
    }


def test_update_cuts_a_version_and_activate_rolls_back():
    session = DummySession(
        responses=[
            {"payload": {**AGENT_PAYLOAD, "version": 2, "current_version_id": "agv_2"}},
            {"payload": AGENT_PAYLOAD},
        ]
    )
    client = make_client(session)

    updated = client.agents.update(
        "agt_1", name="support-bot", model="gpt-5", instructions="Be brief."
    )
    rolled_back = client.agents.activate_version("agt_1", 1)

    assert updated["version"] == 2
    assert rolled_back["version"] == 1
    assert session.calls[0]["method"] == "PUT"
    assert session.calls[1]["url"] == f"{BASE_URL}/agents/agt_1/versions/1/activate"


# ============================================================================
# Pagination: has_more, after_seq, before_seq
# ============================================================================


def test_iter_all_follows_has_more_and_stops_when_it_is_false():
    session = DummySession(
        responses=[
            {"payload": {"data": [AGENT_PAYLOAD, AGENT_PAYLOAD], "has_more": True}},
            {"payload": {"data": [AGENT_PAYLOAD], "has_more": False}},
        ]
    )
    client = make_client(session)

    agents = list(client.agents.iter_all(page_size=2))

    assert len(agents) == 3
    assert len(session.calls) == 2
    assert session.calls[0]["params"]["offset"] == 0
    assert session.calls[1]["params"]["offset"] == 2


def test_iter_all_makes_no_extra_call_when_the_first_page_is_the_last():
    session = DummySession(payload={"data": [AGENT_PAYLOAD], "has_more": False})
    client = make_client(session)

    assert len(list(client.agents.iter_all())) == 1
    assert len(session.calls) == 1


def test_run_events_page_forward_with_after_seq():
    events_page = {
        "data": [
            {"seq": 1, "event": "run.started", "data": {"run_id": "run_1"}},
            {"seq": 2, "event": "message.completed", "data": {"text": "hi"}},
        ],
        "events_version": "1",
    }
    session = DummySession(
        responses=[
            {"payload": events_page},
            {"payload": {"data": [], "events_version": "1"}},
        ]
    )
    client = make_client(session)

    items = list(client.runs.iter_events("run_1", page_size=2))

    assert [item["seq"] for item in items] == [1, 2]
    assert session.calls[0]["params"] == {"after_seq": 0, "limit": 2}
    assert session.calls[1]["params"] == {"after_seq": 2, "limit": 2}


def test_session_transcript_pages_backward_with_before_seq():
    def page(seqs):
        return {
            "session": {
                "id": "ses_1",
                "object": "session",
                "end_user_id": "usr_8837",
                "status": "idle",
                "message_count": 3,
                "created_at": "2026-08-09T00:00:00Z",
            },
            "messages": [
                {
                    "seq": seq,
                    "role": "user",
                    "item": {"text": f"m{seq}"},
                    "created_at": "2026-08-09T00:00:00Z",
                }
                for seq in seqs
            ],
        }

    session = DummySession(
        responses=[{"payload": page([3, 4])}, {"payload": page([2])}]
    )
    client = make_client(session)

    messages = list(client.sessions.iter_messages("ses_1", page_size=2))

    assert [message["seq"] for message in messages] == [4, 3, 2]
    assert "before_seq" not in session.calls[0]["params"]
    assert session.calls[1]["params"]["before_seq"] == 3


# ============================================================================
# Money
# ============================================================================


def test_run_usage_cost_is_a_decimal_not_a_float():
    session = DummySession(payload=RUN_PAYLOAD)
    client = make_client(session)

    run = client.runs.create(
        "agt_1", input="Where is my order?", end_user_id="usr_8837"
    )

    cost = run["usage"]["cost_usd"]
    assert isinstance(cost, Decimal)
    assert not isinstance(cost, float)
    assert cost == Decimal("0.000450")
    # The exactness that a float would lose: 10,000 sub-cent runs sum cleanly.
    assert sum([cost] * 10_000) == Decimal("4.500000")


def test_end_user_budget_fields_are_decimals():
    session = DummySession(
        payload={
            "end_user_id": "usr_8837",
            "object": "end_user",
            "first_activity_at": "2026-08-01T00:00:00Z",
            "budget": {
                "cap_usd": "0.500000",
                "source": "override",
                "window_start": "2026-08-01T00:00:00Z",
                "window_resets_at": "2026-08-31T00:00:00Z",
                "spent_usd": "0.010450",
                "remaining_usd": "0.489550",
            },
            "created_at": "2026-08-01T00:00:00Z",
        }
    )
    client = make_client(session)

    budget = client.end_users.get("usr_8837")["budget"]

    assert budget["cap_usd"] == Decimal("0.500000")
    assert budget["spent_usd"] == Decimal("0.010450")
    assert budget["remaining_usd"] == Decimal("0.489550")
    assert all(
        isinstance(budget[key], Decimal)
        for key in ("cap_usd", "spent_usd", "remaining_usd")
    )


def test_budget_writes_go_out_as_strings_never_floats():
    assert to_money_string(Decimal("0.000450")) == "0.000450"
    assert to_money_string("1.25") == "1.25"
    assert to_money_string(5) == "5"  # int is exact, and still goes out as a string
    with pytest.raises(TypeError):
        to_money_string(True)


@pytest.mark.parametrize("amount", [0.5, 5.0, 0.1 + 0.2, 1e-7])
def test_a_float_budget_is_refused_rather_than_quietly_transmitted(amount):
    """This function used to accept floats "for convenience", routing them
    through repr(): 0.1 + 0.2 went out as "0.30000000000000004" and 1e-7 as
    "1e-7", which the API rejects outright. The convenience was sending the
    caller's rounding error somewhere it could not be undone.

    0.5 and 5.0 are refused too. Sorting representable floats from lossy ones
    is the trap — a caller passing floats eventually passes a lossy one.
    """
    with pytest.raises(TypeError) as exc:
        to_money_string(amount)
    assert "cannot be a float" in str(exc.value)


def test_the_refusal_does_not_hand_back_the_caller_s_own_rounding_error():
    """repr(0.1 + 0.2) is "0.30000000000000004". Quoting it as the suggested
    fix would recommend exactly the value the refusal exists to prevent."""
    message = str(pytest.raises(TypeError, to_money_string, 0.1 + 0.2).value)
    assert "0.30000000000000004" not in message.split("cannot hold")[1]
    assert '"5.00"' in message  # a worked example instead


def test_end_user_update_only_sends_the_fields_you_pass():
    session = DummySession(
        responses=[
            {"payload": {"end_user_id": "usr_8837"}},
            {"payload": {"end_user_id": "usr_8837"}},
            {"payload": {"end_user_id": "usr_8837"}},
        ]
    )
    client = make_client(session)

    client.end_users.update("usr_8837", budget_cap_usd=Decimal("0.50"))
    client.end_users.update("usr_8837", metadata={"plan": "free"})
    client.end_users.clear_budget("usr_8837")

    assert session.calls[0]["json"] == {"budget_cap_usd": "0.50"}
    assert session.calls[1]["json"] == {"metadata": {"plan": "free"}}
    assert session.calls[2]["json"] == {"budget_cap_usd": None}


# ============================================================================
# Idempotency and retries
# ============================================================================


def test_run_create_sends_the_idempotency_key_header():
    session = DummySession(payload=RUN_PAYLOAD)
    client = make_client(session)

    client.runs.create(
        "agt_1",
        input="Where is my order?",
        end_user_id="usr_8837",
        idempotency_key="order-status-42",
    )

    assert session.calls[0]["headers"] == {"Idempotency-Key": "order-status-42"}


def test_replaying_a_key_returns_the_stored_run_without_running_again():
    session = DummySession(payload=RUN_PAYLOAD)
    client = make_client(session)

    first = client.runs.create(
        "agt_1", input="Hi", end_user_id="usr_8837", idempotency_key="k-1"
    )
    replay = client.runs.create(
        "agt_1", input="Hi", end_user_id="usr_8837", idempotency_key="k-1"
    )

    assert first["run_id"] == replay["run_id"] == "run_1"
    assert [call["headers"]["Idempotency-Key"] for call in session.calls] == [
        "k-1",
        "k-1",
    ]


def test_session_busy_retries_with_one_key_and_honours_retry_after():
    session = DummySession(
        responses=[
            {
                "status_code": 409,
                "payload": {
                    "detail": {"code": "session_busy", "message": "Run in flight."}
                },
                "headers": {"Retry-After": "0"},
            },
            {"payload": RUN_PAYLOAD},
        ]
    )
    client = make_client(session)

    run = client.runs.create("agt_1", input="Hi", end_user_id="usr_8837", max_retries=1)

    assert run["run_id"] == "run_1"
    keys = [call["headers"]["Idempotency-Key"] for call in session.calls]
    # A retry without a key could charge the end user twice, so one is made.
    assert len(keys) == 2 and keys[0] == keys[1] and keys[0]


def test_session_busy_is_raised_when_retries_run_out():
    session = DummySession(
        status_code=409,
        payload={"detail": {"code": "session_busy", "message": "Run in flight."}},
    )
    client = make_client(session)

    with pytest.raises(SessionBusyError) as excinfo:
        client.runs.create("agt_1", input="Hi", end_user_id="usr_8837")

    assert excinfo.value.retryable is True
    assert excinfo.value.code == "session_busy"
    assert excinfo.value.status_code == 409


# ============================================================================
# Typed errors
# ============================================================================


@pytest.mark.parametrize(
    "status_code,code,expected",
    [
        (402, "budget_exceeded", BudgetExceededError),
        (402, None, BudgetExceededError),
        (422, "model_requires_own_key", ModelRequiresOwnKeyError),
        (422, "config_key_not_allowed", ConfigKeyNotAllowedError),
    ],
)
def test_error_codes_raise_their_own_exception_type(status_code, code, expected):
    detail = {"code": code, "message": "Refused."} if code else "Refused."
    session = DummySession(status_code=status_code, payload={"detail": detail})
    client = make_client(session)

    with pytest.raises(expected) as excinfo:
        client.runs.create("agt_1", input="Hi", end_user_id="usr_8837")

    assert isinstance(excinfo.value, ManagedAgentError)
    assert excinfo.value.status_code == status_code


def test_unknown_error_codes_still_raise_the_standard_exception():
    session = DummySession(
        status_code=422,
        payload={"detail": {"code": "something_new", "message": "Refused."}},
    )
    client = make_client(session)

    from celesto.sdk.exceptions import CelestoValidationError

    with pytest.raises(CelestoValidationError):
        client.runs.create("agt_1", input="Hi", end_user_id="usr_8837")


# ============================================================================
# The event stream
# ============================================================================

# A whole run on the wire, including one event name this SDK has never heard
# of. Deltas carry no id: they are not stored, so they are not resume points.
SSE_BODY = """\
id: 1
event: run.started
data: {"run_id":"run_1","end_user_id":"usr_8837","model":"openai/gpt-5.4-mini"}

: keep-alive

event: message.delta
data: {"text":"Your order ","turn":1}

event: message.delta
data: {"text":"ships tomorrow.","turn":1}

id: 2
event: reasoning.delta
data: {"text":"an event from a future server"}

id: 3
event: tool.call
data: {"call_id":"call_1","name":"lookup_order","args":{"id":"42"},"turn":1}

id: 4
event: usage
data: {"turn":1,"model":"openai/gpt-5.4-mini","input_tokens":120,"output_tokens":32,"total_tokens":152,"cost_usd":"0.000450"}

id: 5
event: run.completed
data: {"run_id":"run_1","status":"completed","output":"Your order ships tomorrow.","turn_count":1,"usage":{"input_tokens":120,"output_tokens":32,"total_tokens":152,"cost_usd":"0.000450"}}

"""


def test_unknown_event_names_are_ignored():
    events = list(iter_run_events(SSE_BODY.splitlines()))

    names = [event.name for event in events]
    assert "reasoning.delta" not in names
    assert names == [
        "run.started",
        "message.delta",
        "message.delta",
        "tool.call",
        "usage",
        "run.completed",
    ]


def test_every_frame_is_parsed_even_the_ones_that_are_dropped():
    # The frames exist on the wire; it is the mapping to run events that drops
    # the unknown one. Keeping that seam visible is the forward-compat contract.
    frames = list(iter_sse_frames(SSE_BODY.splitlines()))
    assert [frame.event for frame in frames if frame.event] == [
        "run.started",
        "message.delta",
        "message.delta",
        "reasoning.delta",
        "tool.call",
        "usage",
        "run.completed",
    ]


def test_delta_frames_carry_no_sequence_number():
    events = {event.name: event for event in iter_run_events(SSE_BODY.splitlines())}

    assert events["message.delta"].seq is None
    assert events["run.started"].seq == 1
    assert events["run.completed"].seq == 5


def test_event_money_is_a_decimal():
    events = {event.name: event for event in iter_run_events(SSE_BODY.splitlines())}

    assert events["usage"].data["cost_usd"] == Decimal("0.000450")
    assert isinstance(events["usage"].data["cost_usd"], Decimal)
    assert events["run.completed"].data["usage"]["cost_usd"] == Decimal("0.000450")
    assert events["run.completed"].cost_usd == Decimal("0.000450")


def test_event_helpers_read_text_and_terminal_status():
    events = list(iter_run_events(SSE_BODY.splitlines()))
    deltas = [event for event in events if event.name == "message.delta"]

    assert "".join(event.text for event in deltas) == "Your order ships tomorrow."
    assert events[-1].is_terminal is True
    assert events[0].is_terminal is False


def test_a_malformed_data_line_is_dropped_rather_than_crashing_the_stream():
    body = """\
event: message.delta
data: {not json

event: message.completed
data: {"text":"ok","turn":1}

"""

    events = list(iter_run_events(body.splitlines()))

    assert [event.name for event in events] == ["message.completed"]


def test_stream_over_http_yields_events_and_sets_the_stream_flag():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        return httpx.Response(
            200,
            content=SSE_BODY.encode(),
            headers={
                "content-type": "text/event-stream",
                "X-Celesto-Events-Version": "1",
            },
        )

    client = sse_client(handler)

    events = list(
        client.runs.stream(
            "agt_1",
            input="Where is my order?",
            end_user_id="usr_8837",
            idempotency_key="k-9",
        )
    )

    import json

    body = json.loads(seen["body"])
    assert body["stream"] is True
    assert body["end_user_id"] == "usr_8837"
    assert seen["idempotency_key"] == "k-9"
    assert seen["url"] == f"{BASE_URL}/agents/agt_1/runs"
    assert [event.name for event in events][-1] == "run.completed"
    assert all(isinstance(event, RunEvent) for event in events)
    assert "reasoning.delta" not in [event.name for event in events]


def test_stream_raises_the_typed_error_when_the_run_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={"detail": {"code": "budget_exceeded", "message": "Out of budget."}},
        )

    client = sse_client(handler)

    with pytest.raises(BudgetExceededError):
        list(client.runs.stream("agt_1", input="Hi", end_user_id="usr_8837"))


def test_a_failed_run_arrives_as_an_event_not_an_exception():
    body = """\
id: 9
event: run.failed
data: {"run_id":"run_1","status":"failed","error_code":"budget_exceeded","error":"Budget exhausted mid-run.","turn_count":2,"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2,"cost_usd":"0.500000"}}

"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/event-stream"}
        )

    client = sse_client(handler)
    events = list(client.runs.stream("agt_1", input="Hi", end_user_id="usr_8837"))

    assert len(events) == 1
    assert events[0].name == "run.failed"
    assert events[0].is_terminal is True
    assert events[0].data["error_code"] == "budget_exceeded"
    assert events[0].cost_usd == Decimal("0.500000")


# ============================================================================
# Runtime settings
# ============================================================================


def test_runtime_settings_round_trip():
    session = DummySession(
        responses=[
            {
                "payload": {
                    "organization_id": "org_1",
                    "default_end_user_budget_usd": "0.500000",
                }
            },
            {
                "payload": {
                    "organization_id": "org_1",
                    "default_end_user_budget_usd": "1.000000",
                }
            },
        ]
    )
    client = make_client(session)

    current = client.settings.get()
    updated = client.settings.update(default_end_user_budget_usd=Decimal("1.00"))

    assert current["default_end_user_budget_usd"] == Decimal("0.500000")
    assert updated["default_end_user_budget_usd"] == Decimal("1.000000")
    assert session.calls[1]["json"] == {"default_end_user_budget_usd": "1.00"}
