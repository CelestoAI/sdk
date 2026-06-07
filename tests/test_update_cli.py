from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from celesto import main


def test_update_runs_pip_upgrade(monkeypatch):
    runner = CliRunner()
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess:
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(main.sys, "executable", "/usr/bin/python")
    monkeypatch.setattr(main.subprocess, "run", fake_run)

    result = runner.invoke(main.app, ["update"])

    assert result.exit_code == 0
    assert calls == [
        (["/usr/bin/python", "-m", "pip", "install", "--upgrade", "celesto"], True)
    ]
    assert "Celesto is up to date or has been updated." in result.output


def test_update_prints_recovery_command_when_pip_fails(monkeypatch):
    runner = CliRunner()

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    result = runner.invoke(main.app, ["update"])

    assert result.exit_code == 1
    assert "Could not update Celesto." in result.output
    assert "python -m pip install --upgrade celesto" in result.output
