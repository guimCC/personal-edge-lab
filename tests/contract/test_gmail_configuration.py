from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_edge_lab.apps.email_triage_cli import config
from personal_edge_lab.apps.email_triage_cli.config import (
    ConfigurationError,
    GmailAuthorizationSettings,
    GmailFetchSettings,
    MailboxTriageSettings,
    TriageHistorySettings,
)
from personal_edge_lab.infrastructure.gmail.oauth import GMAIL_READONLY_SCOPE


def _private_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def _client_value(secret: str = "client-secret-sentinel") -> dict[str, object]:
    return {
        "installed": {
            "client_id": "client-id.apps.googleusercontent.com",
            "client_secret": secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _token_value(token: str = "access-token-sentinel") -> dict[str, object]:
    return {
        "token": token,
        "refresh_token": "refresh-token-sentinel",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "client-secret-sentinel",
        "scopes": [GMAIL_READONLY_SCOPE],
    }


def _configure_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    client = _private_json(tmp_path / "client.json", _client_value())
    token = _private_json(tmp_path / "token.json", _token_value())
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(token))
    return client, token


def test_authorization_settings_work_while_retrieval_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _client, token = _configure_files(monkeypatch, tmp_path)
    monkeypatch.setenv("GMAIL_READ_ENABLED", "false")

    settings = GmailAuthorizationSettings.from_env()

    assert settings.token_file == token
    assert settings.callback_port == 8765


def test_fetch_settings_freeze_wp6_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_files(monkeypatch, tmp_path)
    monkeypatch.setenv("GMAIL_READ_ENABLED", "true")

    settings = GmailFetchSettings.from_env()

    assert settings.timeout_seconds == 10
    assert settings.default_batch_size == 10
    assert settings.max_message_bytes == 262_144
    assert settings.max_normalized_chars == 8000


def test_fetch_requires_explicit_enablement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_files(monkeypatch, tmp_path)
    monkeypatch.setenv("GMAIL_READ_ENABLED", "false")

    with pytest.raises(ConfigurationError, match="GMAIL_READ_ENABLED"):
        GmailFetchSettings.from_env()


def test_mailbox_triage_requires_its_own_gate_before_other_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_TRIAGE_ENABLED", "false")
    with pytest.raises(ConfigurationError, match="GMAIL_TRIAGE_ENABLED"):
        MailboxTriageSettings.from_env()


def test_history_requires_only_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("GMAIL_READ_ENABLED", "false")
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")

    settings = TriageHistorySettings.from_env()

    assert settings.database_path == database


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("GMAIL_TIMEOUT_SECONDS", "0", "greater than zero"),
        ("GMAIL_TIMEOUT_SECONDS", "61", "must not exceed 60"),
        ("GMAIL_DEFAULT_BATCH_SIZE", "26", "must not exceed 25"),
        ("GMAIL_MAX_MESSAGE_BYTES", "1048577", "must not exceed 1048576"),
        ("GMAIL_MAX_NORMALIZED_CHARS", "8001", "must not exceed 8000"),
    ],
)
def test_fetch_configuration_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
    message: str,
) -> None:
    _configure_files(monkeypatch, tmp_path)
    monkeypatch.setenv("GMAIL_READ_ENABLED", "true")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=message):
        GmailFetchSettings.from_env()


def test_private_files_must_be_absolute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _private_json(tmp_path / "client.json", _client_value())
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", "client.json")
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError, match="absolute"):
        GmailAuthorizationSettings.from_env()


def test_private_files_must_not_be_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_client = _private_json(tmp_path / "real-client.json", _client_value())
    client_link = tmp_path / "client.json"
    client_link.symlink_to(real_client)
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client_link))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError, match="symbolic link"):
        GmailAuthorizationSettings.from_env()


def test_private_files_require_mode_0600(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _private_json(tmp_path / "client.json", _client_value())
    client.chmod(0o644)
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError, match="0600"):
        GmailAuthorizationSettings.from_env()


def test_private_files_must_be_owned_by_current_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _private_json(tmp_path / "client.json", _client_value())
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(config.os, "geteuid", lambda: client.stat().st_uid + 1)

    with pytest.raises(ConfigurationError, match="owned by the current user"):
        GmailAuthorizationSettings.from_env()


def test_private_files_must_be_readable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _private_json(tmp_path / "client.json", _client_value())
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(config.os, "access", lambda *_args: False)

    with pytest.raises(ConfigurationError, match="readable"):
        GmailAuthorizationSettings.from_env()


def test_missing_client_file_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError, match="readable private file"):
        GmailAuthorizationSettings.from_env()


def test_client_path_must_not_be_a_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(tmp_path))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError, match="file, not a directory"):
        GmailAuthorizationSettings.from_env()


def test_client_must_be_a_desktop_oauth_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _private_json(tmp_path / "client.json", {"web": {}})
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError, match="Desktop OAuth"):
        GmailAuthorizationSettings.from_env()


def test_token_must_contain_only_readonly_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, token = _configure_files(monkeypatch, tmp_path)
    value = _token_value()
    value["scopes"] = [
        GMAIL_READONLY_SCOPE,
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    _private_json(token, value)
    monkeypatch.setenv("GMAIL_READ_ENABLED", "true")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))

    with pytest.raises(ConfigurationError, match="only the Gmail read-only scope"):
        GmailFetchSettings.from_env()


def test_malformed_private_json_error_never_contains_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = "client-secret-must-never-appear"
    client = tmp_path / "client.json"
    client.write_text(f'{{"installed": {{"client_secret": "{sentinel}"', encoding="utf-8")
    client.chmod(0o600)
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(ConfigurationError) as caught:
        GmailAuthorizationSettings.from_env()

    assert sentinel not in str(caught.value)
