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
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("stored-key", "keyring")
    )

    assert _get_api_key() == "stored-key"
    captured = capsys.readouterr()
    assert "Key CELESTO_API_KEY not found in .env" not in captured.out
    assert "Key CELESTO_API_KEY not found in .env" not in captured.err


def test_get_api_key_prefers_explicit_value_over_saved_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("stored-key", "keyring")
    )

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


def test_status_reports_missing_saved_key(monkeypatch, tmp_path):
    runner = CliRunner()
    # chdir away from the repo: a stray .env would otherwise supply a real key.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: (None, None)
    )

    result = runner.invoke(auth.app, ["status"])

    assert result.exit_code == 0
    assert "No saved API key was found. Run celesto auth login." in result.output


def test_token_returns_saved_key_for_local_integrations(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(auth, "load_api_key", lambda base_url=None: "stored-key")

    result = runner.invoke(auth.app, ["token"])

    assert result.exit_code == 0
    assert result.output.strip() == "stored-key"


def test_token_reports_missing_saved_key(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(auth, "load_api_key", lambda base_url=None: None)

    result = runner.invoke(auth.app, ["token"])

    assert result.exit_code == 1
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


# --- Credential provenance -------------------------------------------------
#
# API keys are bound to a single organization, so the *source* a key is
# resolved from decides which tenant a command touches. A .env file in the
# working directory outranks a saved login, which means the same command run
# from two directories can hit two different organizations.


def _write_env_file(tmp_path, key: str) -> None:
    (tmp_path / ".env").write_text(f"CELESTO_API_KEY={key}\n", encoding="utf-8")


def test_resolve_cli_credential_prefers_argument(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setenv("CELESTO_API_KEY", "env-key")

    resolved = auth.resolve_cli_credential(api_key="explicit-key")

    assert resolved.api_key == "explicit-key"
    assert resolved.origin == "argument"
    assert resolved.describe_source() == "the --api-key option"


def test_resolve_cli_credential_prefers_env_var_over_env_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setenv("CELESTO_API_KEY", "env-key")

    resolved = auth.resolve_cli_credential()

    assert resolved.api_key == "env-key"
    assert resolved.origin == "environment"


def test_resolve_cli_credential_env_file_outranks_saved_login(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("saved-key", "keyring")
    )

    resolved = auth.resolve_cli_credential()

    assert resolved.api_key == "dotenv-key"
    assert resolved.origin == "env_file"


def test_env_file_override_warns_and_names_the_file(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("saved-key", "keyring")
    )
    monkeypatch.setattr(auth, "_ENV_FILE_OVERRIDE_WARNED", False)

    auth.resolve_cli_credential()

    captured = capsys.readouterr()
    # The warning must go to stderr so `--json` output stays machine-parseable.
    assert "overrides your saved login" in captured.err
    assert ".env" in captured.err
    assert captured.out == ""


def test_no_warning_when_env_file_matches_saved_login(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    _write_env_file(tmp_path, "same-key")
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("same-key", "keyring")
    )
    monkeypatch.setattr(auth, "_ENV_FILE_OVERRIDE_WARNED", False)

    auth.resolve_cli_credential()

    assert "overrides your saved login" not in capsys.readouterr().err


def test_no_warning_when_no_saved_login_exists(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: (None, None)
    )
    monkeypatch.setattr(auth, "_ENV_FILE_OVERRIDE_WARNED", False)

    auth.resolve_cli_credential()

    assert "overrides your saved login" not in capsys.readouterr().err


def test_resolve_cli_credential_falls_back_to_saved_login(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("saved-key", "file")
    )

    resolved = auth.resolve_cli_credential()

    assert resolved.api_key == "saved-key"
    assert resolved.origin == "saved"
    assert resolved.describe_source() == "your saved login (credentials file)"


def test_load_api_key_with_store_reports_keyring(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        auth.keyring, "get_password", lambda service, account: "stored-key"
    )

    assert auth.load_api_key_with_store("https://api.example.test/v1") == (
        "stored-key",
        "keyring",
    )


def test_load_api_key_with_store_reports_file_when_keyring_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def raise_keyring_error(service: str, account: str) -> str:
        raise KeyringError("no keyring")

    monkeypatch.setattr(auth.keyring, "get_password", raise_keyring_error)
    credentials_dir = tmp_path / "celesto"
    credentials_dir.mkdir(parents=True, exist_ok=True)
    (credentials_dir / "credentials.json").write_text(
        json.dumps({"api_key:https://api.example.test/v1": "file-key"}),
        encoding="utf-8",
    )

    assert auth.load_api_key_with_store("https://api.example.test/v1") == (
        "file-key",
        "file",
    )


# --- Status output ---------------------------------------------------------


def test_status_shows_source_and_organization(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("saved-key", "keyring")
    )
    monkeypatch.setattr(
        auth,
        "resolve_active_organization",
        lambda api_key, base_url=None: {"id": "org-1", "name": "Celesto prod"},
    )

    result = runner.invoke(auth.app, ["status"])

    assert result.exit_code == 0
    assert "your saved login (system keyring)" in result.output
    assert "Celesto prod (org-1)" in result.output


def test_status_flags_env_file_override_with_both_organizations(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setattr(
        auth, "load_api_key_with_store", lambda base_url=None: ("saved-key", "keyring")
    )
    monkeypatch.setattr(auth, "_ENV_FILE_OVERRIDE_WARNED", True)

    organizations = {
        "dotenv-key": {"id": "org-personal", "name": "Aniket personal"},
        "saved-key": {"id": "org-prod", "name": "Celesto prod"},
    }
    monkeypatch.setattr(
        auth,
        "resolve_active_organization",
        lambda api_key, base_url=None: organizations[api_key],
    )

    result = runner.invoke(auth.app, ["status"])

    assert result.exit_code == 0
    assert "Aniket personal (org-personal)" in result.output
    assert "overrides your saved login" in result.output
    assert "Celesto prod (org-prod)" in result.output


# --- Saved credentials are keyed by API URL --------------------------------
#
# Credentials are stored per API URL, so resolution has to look up the endpoint
# the command actually targets. Reading the default URL's entry while reporting
# a different one would show the wrong organization.


def test_resolve_cli_credential_looks_up_saved_login_for_the_given_base_url(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    seen = []

    def fake_load(base_url=None):
        seen.append(base_url)
        return ("staging-key", "keyring")

    monkeypatch.setattr(auth, "load_api_key_with_store", fake_load)

    resolved = auth.resolve_cli_credential(base_url="https://api.example.test/v1")

    assert resolved.api_key == "staging-key"
    assert seen == ["https://api.example.test/v1"]


def test_env_file_override_warning_compares_against_the_same_base_url(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    _write_env_file(tmp_path, "dotenv-key")
    monkeypatch.setattr(auth, "_ENV_FILE_OVERRIDE_WARNED", False)
    seen = []

    def fake_load(base_url=None):
        seen.append(base_url)
        return ("staging-key", "keyring")

    monkeypatch.setattr(auth, "load_api_key_with_store", fake_load)

    auth.resolve_cli_credential(base_url="https://api.example.test/v1")

    assert seen == ["https://api.example.test/v1"]
    assert "overrides your saved login" in capsys.readouterr().err


def test_status_resolves_saved_login_for_the_requested_base_url(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CELESTO_API_KEY", raising=False)
    seen = []

    def fake_load(base_url=None):
        seen.append(base_url)
        return ("staging-key", "keyring")

    monkeypatch.setattr(auth, "load_api_key_with_store", fake_load)
    monkeypatch.setattr(
        auth,
        "resolve_active_organization",
        lambda api_key, base_url=None: {"id": "org-staging", "name": "Staging"},
    )

    result = runner.invoke(
        auth.app, ["status", "--base-url", "https://api.example.test/v1"]
    )

    assert result.exit_code == 0
    assert seen == ["https://api.example.test/v1"]
    assert "https://api.example.test/v1" in result.output
    assert "Staging (org-staging)" in result.output
