import httpx
import pytest

from celesto.sdk import Celesto
from celesto.sdk.exceptions import CelestoValidationError


class DummySession:
    def __init__(self, *, status_code: int = 200, payload=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.calls = []
        self.timeout = httpx.Timeout(connect=10, read=120, write=10, pool=10)

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            self.status_code,
            json=self.payload,
            request=httpx.Request(method, url),
        )

    def close(self):
        pass


def test_sdk_exposes_service_clients():
    client = Celesto("test-key", base_url="http://localhost:8500/v1")
    assert hasattr(client, "deployment")
    assert hasattr(client, "gatekeeper")
    assert hasattr(client, "computers")


def test_computers_create_sends_only_explicit_overrides():
    session = DummySession(
        status_code=201,
        payload={
            "id": "cmp_1",
            "name": "curie",
            "status": "creating",
            "vcpus": 1,
            "ram_mb": 1024,
            "disk_size_mb": 15360,
            "image": "ubuntu-desktop-24.04",
            "template_id": "coding-agent",
            "template_version": "latest",
            "created_at": "2026-06-07T00:00:00Z",
        },
    )
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.create(
        template_id="coding-agent",
        disk_size_mb=15360,
    )

    assert result["template_id"] == "coding-agent"
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"] == "https://api.example.test/v1/computers"
    assert session.calls[0]["json"] == {
        "disk_size_mb": 15360,
        "template_id": "coding-agent",
    }
    assert session.calls[0]["timeout"].read == 600
    assert session.timeout.read == 120


def test_computers_create_with_no_args_uses_backend_defaults():
    session = DummySession(status_code=201, payload={})
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    client.computers.create()

    assert session.calls[0]["json"] == {}


def test_computers_create_rejects_conflicting_aliases():
    client = Celesto("test-key", base_url="https://api.example.test/v1")

    with pytest.raises(CelestoValidationError):
        client.computers.create(cpus=1, vcpus=2)

    with pytest.raises(CelestoValidationError):
        client.computers.create(memory=1024, ram_mb=2048)


def test_computers_list_templates_hits_backend_endpoint():
    session = DummySession(
        payload=[
            {
                "id": "scratch",
                "display_name": "Scratch",
                "description": "Minimal VM",
                "default_vcpus": 1,
                "default_ram_mb": 512,
                "default_disk_size_mb": 7168,
                "version": "latest",
                "experimental": False,
            }
        ]
    )
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    templates = client.computers.list_templates()

    assert templates[0]["id"] == "scratch"
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://api.example.test/v1/computers/templates"


def test_computers_list_preserves_default_unfiltered_request():
    session = DummySession(payload={"computers": [], "count": 0})
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.list()

    assert result["count"] == 0
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://api.example.test/v1/computers"
    assert session.calls[0]["params"] is None


def test_computers_list_sends_filters_as_query_params():
    session = DummySession(payload={"computers": [], "count": 0})
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    client.computers.list(
        status="running",
        template_id="browser-agent",
        project_id="proj_123",
        limit=5,
    )

    assert session.calls[0]["params"] == {
        "status": "running",
        "template_id": "browser-agent",
        "project_id": "proj_123",
        "limit": 5,
    }


def test_computers_exec_uses_per_request_read_timeout_without_mutating_default():
    session = DummySession(payload={"exit_code": 0, "stdout": "ok\n", "stderr": ""})
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.exec("cmp_123", "sleep 1", timeout=60)

    assert result["stdout"] == "ok\n"
    assert (
        session.calls[0]["url"] == "https://api.example.test/v1/computers/cmp_123/exec"
    )
    assert session.calls[0]["json"] == {"command": "sleep 1", "timeout": 60}
    assert session.calls[0]["timeout"].read == 75
    assert session.timeout.read == 120


def test_computers_list_command_history_hits_backend_endpoint():
    session = DummySession(payload={"commands": []})
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.list_command_history("cmp_123", limit=10)

    assert result == {"commands": []}
    assert session.calls[0]["method"] == "GET"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/cmp_123/commands"
    )
    assert session.calls[0]["params"] == {"limit": 10}


def test_computers_publish_port_hits_backend_endpoint():
    session = DummySession(
        payload={
            "id": "cpp_123",
            "computer_id": "cmp_123",
            "port": 8000,
            "url": "https://p-test.celesto.ai",
            "status": "published",
            "created_at": "2026-06-07T00:00:00Z",
        }
    )
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.publish_port("curie", port=8000)

    assert result["url"] == "https://p-test.celesto.ai"
    assert session.calls[0]["method"] == "POST"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/curie/published-ports"
    )
    assert session.calls[0]["json"] == {"port": 8000}


def test_computers_list_published_ports_hits_backend_endpoint():
    session = DummySession(payload=[])
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.list_published_ports("cmp_123")

    assert result == []
    assert session.calls[0]["method"] == "GET"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/cmp_123/published-ports"
    )


def test_computers_unpublish_port_hits_backend_endpoint():
    session = DummySession(
        payload={
            "computer_id": "cmp_123",
            "port": 8000,
            "url": None,
            "status": "unpublished",
            "created_at": None,
        }
    )
    client = Celesto("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.unpublish_port("cmp_123", port=8000)

    assert result["status"] == "unpublished"
    assert session.calls[0]["method"] == "DELETE"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/cmp_123/published-ports/8000"
    )
