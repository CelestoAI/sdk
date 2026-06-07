from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from celesto import main


def _one_line(text: str) -> str:
    return " ".join(text.split())


def test_update_runs_pip_upgrade(monkeypatch):
    runner = CliRunner()
    calls: list[tuple[list[str], bool]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.CompletedProcess:
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.sys, "executable", "/usr/bin/python")
    monkeypatch.setattr(main.subprocess, "run", fake_run)

    result = runner.invoke(main.app, ["update"])

    assert result.exit_code == 0
    assert calls == [
        (["/usr/bin/python", "-m", "pip", "--version"], False),
        (["/usr/bin/python", "-m", "pip", "install", "--upgrade", "celesto"], True),
    ]
    assert "Celesto is up to date or has been updated." in result.output


def test_update_uses_uv_when_pip_is_missing(monkeypatch):
    runner = CliRunner()
    calls: list[tuple[list[str], bool]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.CompletedProcess:
        calls.append((command, check))
        return subprocess.CompletedProcess(
            command, 1 if command[-1] == "--version" else 0
        )

    monkeypatch.setattr(main.sys, "executable", "/workspace/.venv/bin/python")
    monkeypatch.setattr(main.subprocess, "run", fake_run)
    monkeypatch.setattr(main, "which", lambda command: "/usr/local/bin/uv")

    result = runner.invoke(main.app, ["update"])

    assert result.exit_code == 0
    assert calls == [
        (["/workspace/.venv/bin/python", "-m", "pip", "--version"], False),
        (
            [
                "/usr/local/bin/uv",
                "pip",
                "install",
                "--python",
                "/workspace/.venv/bin/python",
                "--upgrade",
                "celesto",
            ],
            True,
        ),
    ]
    assert "Using uv instead" in result.output


def test_update_prints_recovery_command_when_update_fails(monkeypatch):
    runner = CliRunner()

    def fake_run(
        command: list[str],
        *,
        check: bool,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.CompletedProcess:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(main.sys, "executable", "/usr/bin/python")
    monkeypatch.setattr(main.subprocess, "run", fake_run)

    result = runner.invoke(main.app, ["update"])

    assert result.exit_code == 1
    assert "Could not update Celesto." in result.output
    assert "uv pip install --python /usr/bin/python --upgrade celesto" in _one_line(
        result.output
    )


def test_update_explains_when_pip_and_uv_are_missing(monkeypatch):
    runner = CliRunner()

    def fake_run(
        command: list[str],
        *,
        check: bool,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(main.sys, "executable", "/workspace/.venv/bin/python")
    monkeypatch.setattr(main.subprocess, "run", fake_run)
    monkeypatch.setattr(main, "which", lambda command: None)

    result = runner.invoke(main.app, ["update"])

    assert result.exit_code == 1
    assert "This Python environment does not have pip." in result.output
    assert (
        "uv pip install --python /workspace/.venv/bin/python --upgrade celesto"
        in _one_line(result.output)
    )
