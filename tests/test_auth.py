from __future__ import annotations

import json

from keyring.errors import KeyringError
from typer.testing import CliRunner

from celesto import auth
from celesto.deployment import _get_api_key


def test_auth_helpers_use_base_url_scoped_keyring(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_set_password(service: str, account: str, password: str) -> None:
        calls.append(("set", service, account, password))

    def fake_get_password(service: str, account: str) -> str:
        calls.append(("get", service, account))
        return "stored-key"

    def fake_delete_password(service: str, account: str) -> None:
        calls.append(("delete", service, account))

    monkeypatch.setattr(auth.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(auth.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(auth.keyring, "delete_password", fake_delete_password)

    auth.save_api_key("secret", "https://api.example.test/v1/")
    assert auth.load_api_key("https://api.example.test/v1") == "stored-key"
    auth.delete_api_key("https://api.example.test/v1")

    assert calls == [
        ("set", "celesto", "api_key:https://api.example.test/v1", "secret"),
        ("get", "celesto", "api_key:https://api.example.test/v1"),
        ("delete", "celesto", "api_key:https://api.example.test/v1"),
    ]


def test_auth_helpers_fall_back_to_local_credentials_file(monkeypatch, tmp_path):
    def raise_keyring_error(*args: object, **kwargs: object) -> None:
        raise KeyringError("no keyring backend")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(auth.keyring, "set_password", raise_keyring_error)
    monkeypatch.setattr(auth.keyring, "get_password", raise_keyring_error)
    monkeypatch.setattr(auth.keyring, "delete_password", raise_keyring_error)

    store = auth.save_api_key("secret", "https://api.example.test/v1/")

    credentials_path = tmp_path / "celesto" / "credentials.json"
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    account = "api_key:https://api.example.test/v1"

    assert store == "file"
    assert credentials_path.stat().st_mode & 0o777 == 0o600
    assert credentials[account] == "secret"
    assert credentials[f"{auth.CREDENTIAL_STORE_PREFERENCE_KEY}:{account}"] == "file"
    assert auth.load_api_key("https://api.example.test/v1") == "secret"

    auth.delete_api_key("https://api.example.test/v1")

    assert not credentials_path.exists()


def test_login_uses_file_fallback_when_keyring_is_unavailable(monkeypatch, tmp_path):
    runner = CliRunner()

    def raise_keyring_error(*args: object, **kwargs: object) -> None:
        raise KeyringError("no keyring backend")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "validate_api_key", lambda api_key, base_url=None: None)
    monkeypatch.setattr(auth.keyring, "set_password", raise_keyring_error)

    result = runner.invoke(
        auth.app,
        ["login", "--api-key", "test-key", "--base-url", "https://api.example.test/v1"],
    )

    assert result.exit_code == 0
    assert "Saved your Celesto API key in a local credentials file" in result.output
    assert auth.load_api_key("https://api.example.test/v1") == "test-key"


def test_login_reports_when_key_cannot_be_saved(monkeypatch, tmp_path):
    runner = CliRunner()

    def raise_keyring_error(*args: object, **kwargs: object) -> None:
        raise KeyringError("no keyring backend")

    def raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("read-only config")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "validate_api_key", lambda api_key, base_url=None: None)
    monkeypatch.setattr(auth.keyring, "set_password", raise_keyring_error)
    monkeypatch.setattr(auth, "_save_file_credentials", raise_os_error)

    result = runner.invoke(
        auth.app,
        ["login", "--api-key", "test-key", "--base-url", "https://api.example.test/v1"],
    )

    assert result.exit_code == 1
    assert "Your API key could not be saved. Set CELESTO_API_KEY" in result.output


def test_get_api_key_uses_saved_key_after_env_and_dotenv_miss(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    monkeypatch.setattr("celesto.deployment.load_api_key", lambda: "stored-key")

    assert _get_api_key() == "stored-key"
    captured = capsys.readouterr()
    assert "Key CELESTO_API_KEY not found in .env" not in captured.out
    assert "Key CELESTO_API_KEY not found in .env" not in captured.err


def test_get_api_key_prefers_explicit_value_over_saved_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("celesto.deployment.load_api_key", lambda: "stored-key")

    assert _get_api_key(api_key="explicit-key") == "explicit-key"


def test_login_validates_and_saves_key(monkeypatch):
    runner = CliRunner()
    events = []

    def fake_validate_api_key(api_key: str, base_url: str | None = None) -> None:
        events.append(("validate", api_key, base_url))

    def fake_save_api_key(api_key: str, base_url: str | None = None) -> None:
        events.append(("save", api_key, base_url))

    monkeypatch.setattr(auth, "validate_api_key", fake_validate_api_key)
    monkeypatch.setattr(auth, "save_api_key", fake_save_api_key)

    result = runner.invoke(
        auth.app,
        ["login", "--api-key", "test-key", "--base-url", "https://api.example.test/v1"],
    )

    assert result.exit_code == 0
    assert "Saved your Celesto API key" in result.output
    assert events == [
        ("validate", "test-key", "https://api.example.test/v1"),
        ("save", "test-key", "https://api.example.test/v1"),
    ]


def test_status_reports_missing_saved_key(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(auth, "load_api_key", lambda base_url=None: None)

    result = runner.invoke(auth.app, ["status"])

    assert result.exit_code == 0
    assert "No saved API key was found. Run celesto auth login." in result.output


def test_logout_removes_saved_key(monkeypatch):
    runner = CliRunner()
    deleted = []
    monkeypatch.setattr(
        auth, "delete_api_key", lambda base_url=None: deleted.append(base_url)
    )

    result = runner.invoke(
        auth.app, ["logout", "--base-url", "https://api.example.test/v1"]
    )

    assert result.exit_code == 0
    assert deleted == ["https://api.example.test/v1"]
    assert "Removed your saved Celesto API key" in result.output
