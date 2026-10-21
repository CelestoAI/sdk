"""Custom templates: the Template resource and its client, against a fake HTTP session."""

import httpx
import pytest

import celesto
from celesto import Computer, Template
from celesto.sdk import CelestoTemplateBuildError
from celesto.sdk.client import _CelestoClient
from celesto.sdk.exceptions import (
    CelestoConflictError,
    CelestoNetworkError,
    CelestoNotFoundError,
    CelestoRateLimitError,
    CelestoServerError,
    CelestoValidationError,
)

BASE = "https://api.example.test/v1"


def _template(**overrides):
    data = {
        "id": "tpl_abc123",
        "name": "data-env",
        "organization_id": "org-1",
        "created_by": "user-1",
        "base_template_id": "coding-agent",
        "base_template_version": "v1",
        "build_script": "pip install pandas",
        "status": "queued",
        "default_vcpus": 2,
        "default_ram_mb": 4096,
        "default_disk_size_mb": 10240,
        "warnings": [],
    }
    data.update(overrides)
    return data


def _log(status, log, offset, size, **extra):
    """A /logs response body."""
    return {"status": status, "log": log, "offset": offset, "size": size, **extra}


class ScriptedSession:
    """Answers each request with the next queued response and records the call.

    A queued item is ``(status, payload)``, ``(status, payload, headers)``, or
    an exception instance to raise from the request.
    """

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, payload, *rest = item
        headers = rest[0] if rest else None
        return httpx.Response(
            status, json=payload, headers=headers, request=httpx.Request(method, url)
        )

    def close(self):
        pass


def _client(*responses):
    client = _CelestoClient("test-key", base_url=BASE)
    session = ScriptedSession(*responses)
    client.session = session
    return client, session


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record wait()'s sleeps instead of sleeping, advancing a fake clock."""
    recorded = []
    clock = [1000.0]

    def fake_sleep(seconds):
        recorded.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("celesto.sdk.template.time.sleep", fake_sleep)
    monkeypatch.setattr("celesto.sdk.template.time.monotonic", lambda: clock[0])
    return recorded


def test_template_is_exported_at_top_level():
    assert celesto.Template is Template


def test_create_sends_script_base_and_default_size():
    client, session = _client(
        (
            201,
            _template(
                warnings=[{"line": 1, "code": "apt_without_yes", "message": "add -y"}]
            ),
        )
    )

    template = Template(
        name="data-env",
        build_script="apt-get install ffmpeg",
        base_template_id="coding-agent",
        default_vcpus=2,
        default_ram_mb=4096,
        default_disk_size_mb=10240,
        client=client,
    )

    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"] == f"{BASE}/templates"
    assert session.calls[0]["json"] == {
        "name": "data-env",
        "build_script": "apt-get install ffmpeg",
        "base_template_id": "coding-agent",
        "default_vcpus": 2,
        "default_ram_mb": 4096,
        "default_disk_size_mb": 10240,
    }
    assert template.id == "tpl_abc123"
    assert template["status"] == "queued"
    assert template.warnings[0]["code"] == "apt_without_yes"


def test_create_leaves_base_and_size_to_the_api_when_omitted():
    client, session = _client((201, _template()))

    Template(name="data-env", build_script="pip install pandas", client=client)

    assert session.calls[0]["json"] == {
        "name": "data-env",
        "build_script": "pip install pandas",
    }


def test_create_rejects_a_partial_default_size_before_calling_the_api():
    client, session = _client()

    with pytest.raises(CelestoValidationError, match="together"):
        Template(name="x", build_script="true", default_vcpus=2, client=client)
    assert session.calls == []


def test_create_closes_the_client_it_made_when_the_api_refuses(monkeypatch):
    client, _ = _client((400, {"detail": "bad name"}))
    closed = []
    client.close = lambda: closed.append(True)
    monkeypatch.setattr(
        "celesto.sdk.template._make_client", lambda **_kwargs: (client, True)
    )

    with pytest.raises(CelestoValidationError):
        Template(name="bad name!", build_script="true")
    assert closed == [True]


def test_create_explains_the_concurrent_build_limit():
    client, _ = _client(
        (
            429,
            {
                "detail": {
                    "error_code": "template_build_limit",
                    "message": "Too many builds",
                }
            },
        )
    )

    with pytest.raises(CelestoRateLimitError, match="2 template builds"):
        Template(name="x", build_script="true", client=client)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: Template.list(client=c),
        lambda c: Template.lint("true", client=c),
        lambda c: Template(name="x", build_script="true", client=c),
    ],
    ids=["list", "lint", "create"],
)
def test_collection_404_says_templates_are_not_enabled(call):
    client, _ = _client((404, {"detail": "Not Found"}))

    with pytest.raises(CelestoNotFoundError, match="not enabled"):
        call(client)


def test_get_404_stays_a_plain_not_found():
    client, _ = _client((404, {"detail": "Template not found"}))

    with pytest.raises(CelestoNotFoundError) as excinfo:
        Template.get("tpl_missing", client=client)
    assert "not enabled" not in str(excinfo.value)


def test_template_ids_are_escaped_in_the_url():
    client, session = _client((200, _template()))

    Template.get("../computers/cmp_1", client=client)

    assert session.calls[0]["url"] == f"{BASE}/templates/..%2Fcomputers%2Fcmp_1"


def test_list_and_lint_return_plain_lists():
    client, session = _client(
        (200, {"templates": [_template()], "count": 1}),
        (
            200,
            {
                "warnings": [
                    {"line": 1, "code": "file_reference", "message": "list packages"}
                ]
            },
        ),
    )

    templates = Template.list(client=client)
    warnings = Template.lint("pip install -r requirements.txt", client=client)

    assert [t["id"] for t in templates] == ["tpl_abc123"]
    assert warnings[0]["code"] == "file_reference"
    assert session.calls[1]["url"] == f"{BASE}/templates/lint"
    assert session.calls[1]["json"] == {
        "build_script": "pip install -r requirements.txt"
    }


# --- wait() and log following -------------------------------------------------


def test_wait_without_on_log_polls_the_template():
    client, session = _client(
        (200, _template(status="building")),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)

    assert template.wait() is template
    assert template.status == "ready"
    assert [c["url"] for c in session.calls] == [f"{BASE}/templates/tpl_abc123"] * 2


def test_wait_with_on_log_makes_one_request_per_poll_and_streams_new_text():
    client, session = _client(
        (200, _log("building", "step 1\n", 0, 7)),
        (200, _log("building", "", 7, 7, unchanged=True)),
        (200, _log("ready", "step 1\nstep 2\n", 0, 14)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    result = template.wait(on_log=chunks.append)

    assert result is template
    assert template.status == "ready"
    assert chunks == ["step 1\n", "step 2\n"]
    # Three log polls, then one read of the finished template.
    assert [c["url"] for c in session.calls] == [
        f"{BASE}/templates/tpl_abc123/logs"
    ] * 3 + [f"{BASE}/templates/tpl_abc123"]
    assert session.calls[0]["params"] is None
    assert session.calls[1]["params"] == {"known_size": 7}


def test_wait_delivers_a_character_split_across_polls_once():
    # The server stored b"abc\xc3" (the first byte of "é"), which decodes to
    # "abc�". The next poll has the whole character and more.
    client, _ = _client(
        (200, _log("building", "abc�", 0, 4)),
        (200, _log("ready", "abcédef\n", 0, 9)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert "".join(chunks) == "abcédef\n"


def test_wait_keeps_invalid_bytes_and_later_text():
    # b"ab\xff\n" is 4 stored bytes but 6 bytes once \xff becomes U+FFFD.
    client, _ = _client(
        (200, _log("building", "ab�\n", 0, 4)),
        (200, _log("building", "ab�\ncd\n", 0, 7)),
        (200, _log("ready", "ab�\ncd\nef\n", 0, 10)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert "".join(chunks) == "ab�\ncd\nef\n"


def test_wait_holding_a_character_does_not_refetch_the_whole_log_each_poll():
    client, session = _client(
        (200, _log("building", "abc�", 0, 4)),
        (200, _log("building", "", 4, 4, unchanged=True)),
        # The build ended without new bytes: one more read without known_size
        # returns the held character whole.
        (200, _log("ready", "", 4, 4, unchanged=True)),
        (200, _log("ready", "abcé", 0, 5)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert "".join(chunks) == "abcé"
    assert [c.get("params") for c in session.calls[:4]] == [
        None,
        {"known_size": 4},
        {"known_size": 4},
        None,
    ]


def test_wait_does_not_retry_or_repeat_when_on_log_raises():
    client, session = _client((200, _log("building", "step 1\n", 0, 7)))
    template = Template._wrap(_template(), client, owns_client=False)
    calls = []

    def on_log(text):
        calls.append(text)
        raise CelestoNetworkError("my sink is down")

    with pytest.raises(CelestoNetworkError, match="my sink"):
        template.wait(on_log=on_log)
    assert calls == ["step 1\n"]
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "kwargs", [{"timeout": float("nan")}, {"poll_interval": float("nan")}]
)
def test_wait_rejects_nan(kwargs):
    client, session = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError):
        template.wait(**kwargs)
    assert session.calls == []


def test_wait_flushes_a_trailing_replacement_character_when_the_build_ends():
    client, _ = _client(
        (200, _log("failed", "boom�", 0, 5)),
        (200, _template(status="failed")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    with pytest.raises(CelestoTemplateBuildError):
        template.wait(on_log=chunks.append)
    assert "".join(chunks) == "boom�"


def test_wait_marks_log_text_the_window_skipped():
    client, _ = _client(
        (200, _log("building", "abc", 0, 3)),
        (200, _log("ready", "xyz", 500, 503, truncated=True)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert chunks[0] == "abc"
    assert "497 bytes" in chunks[1]
    assert chunks[2] == "xyz"


def test_wait_skips_only_what_it_already_delivered_when_the_window_slides():
    client, _ = _client(
        (200, _log("building", "abcdef", 0, 6)),
        (200, _log("ready", "defghi", 3, 9, truncated=True)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert "".join(chunks) == "abcdefghi"


def test_wait_slides_the_window_over_non_ascii_text_without_repeats():
    # The server starts a moved window on a character boundary, so "é" (2
    # bytes) is counted exactly when converting the overlap to characters.
    client, _ = _client(
        (200, _log("building", "aé", 0, 3)),
        (200, _log("ready", "ébc", 1, 5, truncated=True)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert "".join(chunks) == "aébc"


def test_wait_backoff_does_not_overflow_after_many_failed_polls():
    from celesto.sdk.template import _retry_delay

    error = CelestoServerError("down")
    assert _retry_delay(error, 2.0, 5000) == 30.0


def test_wait_starts_over_when_a_new_build_resets_the_log():
    client, _ = _client(
        (200, _log("building", "old build output\n", 0, 17)),
        (200, _log("building", "new\n", 0, 4)),
        (200, _log("ready", "new\nbuild\n", 0, 10)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert "".join(chunks) == "old build output\nnew\nbuild\n"


def test_wait_keeps_going_through_a_transient_log_503():
    client, _ = _client(
        (
            503,
            {
                "detail": {
                    "error_code": "build_log_unavailable",
                    "message": "try again",
                }
            },
        ),
        (200, _log("ready", "done\n", 0, 5)),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    assert template.wait(on_log=chunks.append) is template
    assert chunks == ["done\n"]


def test_wait_waits_out_a_rate_limit_using_retry_after(sleeps):
    client, _ = _client(
        (429, {"detail": "Too Many Requests"}, {"Retry-After": "7"}),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)

    template.wait()

    assert sleeps and sleeps[0] >= 7


def test_wait_keeps_going_through_a_network_error():
    client, _ = _client(
        httpx.ConnectError("connection reset"),
        (200, _template(status="ready")),
    )
    template = Template._wrap(_template(), client, owns_client=False)

    assert template.wait() is template


def test_wait_does_not_retry_a_conflict():
    client, _ = _client((409, {"detail": "conflict"}))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoConflictError):
        template.wait()


def test_wait_times_out_and_names_the_last_error_while_retrying():
    client, _ = _client((503, {"detail": "unavailable"}))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(TimeoutError) as excinfo:
        template.wait(timeout=0)
    assert isinstance(excinfo.value.__cause__, CelestoServerError)


def test_wait_times_out_while_still_building():
    client, _ = _client((200, _template(status="building")))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(TimeoutError, match="still building"):
        template.wait(timeout=0)


def test_wait_never_sleeps_past_the_deadline(sleeps):
    client, _ = _client(
        (200, _template(status="building")),
        (200, _template(status="building")),
    )
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(TimeoutError):
        template.wait(timeout=2, poll_interval=60)
    assert sleeps and all(s <= 2 for s in sleeps)


def test_wait_rejects_a_poll_interval_under_one_second():
    client, session = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError, match="poll_interval"):
        template.wait(poll_interval=0)
    assert session.calls == []


def test_wait_raises_build_error_with_failing_line():
    failure = {
        "line": "pip install nope",
        "line_number": 2,
        "exit_code": 1,
        "hint": "check the package name",
    }
    client, _ = _client((200, _template(status="failed", failure=failure)))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoTemplateBuildError) as excinfo:
        template.wait()

    message = str(excinfo.value)
    assert (
        "line 2" in message
        and "pip install nope" in message
        and "exit code 1" in message
    )
    assert "check the package name" in message
    assert excinfo.value.failure == failure
    assert excinfo.value.template["status"] == "failed"


@pytest.mark.parametrize(
    "extra,expected",
    [
        ({"error": "builder crashed"}, "builder crashed"),
        ({"failure": {"hint": "retry later"}}, "Hint: retry later"),
        ({"failure": "not a dict"}, "build failed"),
        ({}, "build failed"),
    ],
    ids=["error-only", "hint-only", "malformed-failure", "bare"],
)
def test_wait_build_error_message_shapes(extra, expected):
    client, _ = _client((200, _template(status="failed", **extra)))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoTemplateBuildError, match=expected):
        template.wait()


def test_wait_raises_on_needs_rebuild():
    client, _ = _client((200, _template(status="needs_rebuild")))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoTemplateBuildError, match="rebuild"):
        template.wait()


# --- admin routes and errors --------------------------------------------------


def test_edit_rebuild_and_delete_hit_admin_routes():
    client, session = _client(
        (200, _template(build_script="pip install polars")),
        (202, _template(status="queued")),
        (204, None),
    )
    template = Template._wrap(_template(status="ready"), client, owns_client=False)

    template.edit(build_script="pip install polars")
    template.rebuild()
    template.delete()

    assert [(c["method"], c["url"]) for c in session.calls] == [
        ("PATCH", f"{BASE}/templates/tpl_abc123"),
        ("POST", f"{BASE}/templates/tpl_abc123/rebuild"),
        ("DELETE", f"{BASE}/templates/tpl_abc123"),
    ]
    assert session.calls[0]["json"] == {"build_script": "pip install polars"}
    assert template.status == "queued"


def test_rebuild_while_building_raises_a_conflict_that_is_still_a_server_error():
    client, _ = _client(
        (
            409,
            {
                "detail": {
                    "error_code": "template_build_in_progress",
                    "message": "A build is already queued or running",
                }
            },
        )
    )
    template = Template._wrap(_template(status="building"), client, owns_client=False)

    with pytest.raises(CelestoConflictError, match="already queued") as excinfo:
        template.rebuild()
    # Existing `except CelestoServerError` handlers, and the CLI's check for
    # "409" in the message, keep working.
    assert isinstance(excinfo.value, CelestoServerError)
    assert "409" in str(excinfo.value)


def test_rebuild_explains_the_concurrent_build_limit():
    client, _ = _client(
        (429, {"detail": {"error_code": "template_build_limit", "message": "busy"}})
    )
    template = Template._wrap(_template(status="ready"), client, owns_client=False)

    with pytest.raises(CelestoRateLimitError, match="2 template builds"):
        template.rebuild()


def test_edit_needs_a_change():
    client, _ = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError):
        template.edit()


def test_edit_rejects_a_partial_default_size_before_calling_the_api():
    client, session = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError, match="together"):
        template.edit(default_vcpus=2)
    assert session.calls == []


def test_mapping_update_stays_local():
    client, session = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    template.update({"name": "renamed"})

    assert template["name"] == "renamed"
    assert session.calls == []


# --- create_computer ----------------------------------------------------------


def test_create_computer_uses_the_template_id_and_shared_client():
    client, session = _client(
        (201, {"id": "cmp_1", "name": "curie", "status": "creating"})
    )
    template = Template._wrap(_template(status="ready"), client, owns_client=False)

    computer = template.create_computer(cpus=2)

    assert isinstance(computer, Computer)
    assert computer._client is client
    assert session.calls[0]["url"] == f"{BASE}/computers"
    assert session.calls[0]["json"] == {"vcpus": 2, "template_id": "tpl_abc123"}


def test_create_computer_gets_its_own_client_when_the_template_owns_one(monkeypatch):
    client, _ = _client()
    template = Template._wrap(_template(status="ready"), client, owns_client=True)
    made = []

    def fake_create(self, **kwargs):
        made.append(kwargs)
        return {"id": "cmp_1", "status": "creating"}

    monkeypatch.setattr("celesto.sdk.client.Computers.create", fake_create)

    computer = template.create_computer()
    template.close()

    # The computer has its own client with the template's key and URL, so
    # closing the template does not close it.
    assert computer._client is not client
    assert computer._owns_client is True
    assert computer._client.api_key == "test-key"
    assert computer._client.base_url == BASE
    assert made[0]["template_id"] == "tpl_abc123"


def test_create_computer_honors_an_explicit_api_key(monkeypatch):
    client, _ = _client()
    template = Template._wrap(_template(status="ready"), client, owns_client=False)
    monkeypatch.setattr(
        "celesto.sdk.client.Computers.create",
        lambda self, **kwargs: {"id": "cmp_1", "status": "creating"},
    )

    computer = template.create_computer(api_key="other-key")

    assert computer._client is not client
    assert computer._client.api_key == "other-key"


def test_create_computer_before_the_first_build_says_to_wait():
    client, session = _client()
    template = Template._wrap(_template(status="building"), client, owns_client=False)

    with pytest.raises(CelestoValidationError, match="wait"):
        template.create_computer()
    assert session.calls == []


def test_create_computer_while_rebuilding_uses_the_previous_build():
    client, session = _client((201, {"id": "cmp_1", "status": "creating"}))
    template = Template._wrap(
        _template(status="building", rootfs_size_mb=900), client, owns_client=False
    )

    template.create_computer()

    assert session.calls[0]["json"] == {"template_id": "tpl_abc123"}


def test_create_computer_on_needs_rebuild_says_to_rebuild():
    client, session = _client()
    template = Template._wrap(
        _template(status="needs_rebuild", rootfs_size_mb=900),
        client,
        owns_client=False,
    )

    with pytest.raises(CelestoTemplateBuildError, match="rebuild"):
        template.create_computer()
    assert session.calls == []


def test_create_computer_refuses_another_template_id():
    client, _ = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError):
        template.create_computer(template_id="coding-agent")
