import httpx
import pytest

from celesto.sdk import Celesto
from celesto.sdk.exceptions import CelestoValidationError


class DummySession:
    def __init__(self, *, status_code: int = 200, payload=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.calls = []

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
