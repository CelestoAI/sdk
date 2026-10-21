"""Custom templates: the Template resource and its client, against a fake HTTP session."""

import httpx
import pytest

import celesto
from celesto import Computer, Template
from celesto.sdk import CelestoTemplateBuildError
from celesto.sdk.client import _CelestoClient
from celesto.sdk.exceptions import CelestoNotFoundError, CelestoValidationError

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


class ScriptedSession:
    """Answers each request with the next queued (status, payload) and records the call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload, request=httpx.Request(method, url))

    def close(self):
        pass


def _client(*responses):
    client = _CelestoClient("test-key", base_url=BASE)
    session = ScriptedSession(*responses)
    client.session = session
    return client, session


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("celesto.sdk.template.time.sleep", lambda _seconds: None)


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


def test_collection_404_says_templates_are_not_enabled():
    client, _ = _client((404, {"detail": "Not Found"}))

    with pytest.raises(CelestoNotFoundError, match="not enabled"):
        Template.list(client=client)


def test_get_404_stays_a_plain_not_found():
    client, _ = _client((404, {"detail": "Template not found"}))

    with pytest.raises(CelestoNotFoundError) as excinfo:
        Template.get("tpl_missing", client=client)
    assert "not enabled" not in str(excinfo.value)


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


def test_wait_streams_only_new_log_text_and_returns_when_ready():
    client, session = _client(
        (200, _template(status="building")),
        (200, {"status": "building", "log": "step 1\n", "offset": 0, "size": 7}),
        (200, _template(status="building")),
        (
            200,
            {
                "status": "building",
                "log": "",
                "offset": 7,
                "size": 7,
                "unchanged": True,
            },
        ),
        (200, _template(status="ready")),
        (200, {"status": "ready", "log": "step 1\nstep 2\n", "offset": 0, "size": 14}),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    result = template.wait(on_log=chunks.append)

    assert result is template
    assert template.status == "ready"
    assert chunks == ["step 1\n", "step 2\n"]
    # The unchanged poll sent back the size it had already seen.
    assert session.calls[3]["params"] == {"known_size": 7}


def test_wait_delivers_the_window_when_the_log_was_truncated_past_what_was_seen():
    client, _ = _client(
        (200, _template(status="building")),
        (200, {"status": "building", "log": "abc", "offset": 0, "size": 3}),
        (200, _template(status="ready")),
        (
            200,
            {
                "status": "ready",
                "log": "xyz",
                "offset": 500,
                "size": 503,
                "truncated": True,
            },
        ),
    )
    template = Template._wrap(_template(), client, owns_client=False)
    chunks = []

    template.wait(on_log=chunks.append)

    assert chunks == ["abc", "xyz"]


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


def test_wait_raises_on_needs_rebuild():
    client, _ = _client((200, _template(status="needs_rebuild")))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoTemplateBuildError, match="rebuild"):
        template.wait()


def test_wait_times_out_while_still_building():
    client, _ = _client((200, _template(status="building")))
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(TimeoutError, match="still building"):
        template.wait(timeout=0)


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


def test_edit_needs_a_change():
    client, _ = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError):
        template.edit()


def test_mapping_update_stays_local():
    client, session = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    template.update({"name": "renamed"})

    assert template["name"] == "renamed"
    assert session.calls == []


def test_create_computer_uses_the_template_id_and_shared_client():
    client, session = _client(
        (201, {"id": "cmp_1", "name": "curie", "status": "creating"})
    )
    template = Template._wrap(_template(status="ready"), client, owns_client=False)

    computer = template.create_computer(cpus=2)

    assert isinstance(computer, Computer)
    assert session.calls[0]["url"] == f"{BASE}/computers"
    assert session.calls[0]["json"] == {"vcpus": 2, "template_id": "tpl_abc123"}


def test_create_computer_refuses_another_template_id():
    client, _ = _client()
    template = Template._wrap(_template(), client, owns_client=False)

    with pytest.raises(CelestoValidationError):
        template.create_computer(template_id="coding-agent")
