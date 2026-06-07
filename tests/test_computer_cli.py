from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from typer.testing import CliRunner

from celesto import computer


def test_terminal_dimensions_return_rows_then_columns(monkeypatch):
    monkeypatch.setattr(
        computer.os,
        "get_terminal_size",
        lambda: os.terminal_size((120, 30)),
    )

    assert computer._terminal_dimensions() == (30, 120)


class _FakeComputers:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []

    def publish_port(self, computer_id: str, *, port: int = 8000) -> dict:
        self.calls.append(("publish", computer_id, port))
        return {
            "id": "cpp_123",
            "computer_id": "cmp_123",
            "port": port,
            "url": "https://p-test.celesto.ai",
            "status": "published",
            "created_at": "2026-06-07T00:00:00Z",
        }

    def list_published_ports(self, computer_id: str) -> list[dict]:
        self.calls.append(("list", computer_id, None))
        return [
            {
                "id": "cpp_123",
                "computer_id": "cmp_123",
                "port": 8000,
                "url": "https://p-test.celesto.ai",
                "status": "published",
                "created_at": "2026-06-07T00:00:00Z",
            }
        ]

    def unpublish_port(self, computer_id: str, *, port: int = 8000) -> dict:
        self.calls.append(("unpublish", computer_id, port))
        return {
            "computer_id": "cmp_123",
            "port": port,
            "url": None,
            "status": "unpublished",
            "created_at": None,
        }


class _FakeClient:
    def __init__(self) -> None:
        self.computers = _FakeComputers()

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_computer_port_publish_prints_url(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "publish", "curie"])

    assert result.exit_code == 0
    urls = []
    for token in result.output.split():
        parsed = urlparse(token)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(parsed)
    assert any(u.scheme == "https" and u.hostname == "p-test.celesto.ai" for u in urls)
    assert fake_client.computers.calls == [("publish", "curie", 8000)]


def test_computer_port_publish_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "publish", "cmp_123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["url"] == "https://p-test.celesto.ai"
    assert fake_client.computers.calls == [("publish", "cmp_123", 8000)]


def test_computer_port_list_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "list", "cmp_123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["port"] == 8000
    assert fake_client.computers.calls == [("list", "cmp_123", None)]


def test_computer_port_unpublish_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "unpublish", "cmp_123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "unpublished"
    assert fake_client.computers.calls == [("unpublish", "cmp_123", 8000)]
