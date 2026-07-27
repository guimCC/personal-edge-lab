from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from personal_edge_lab.application.ports.email import (
    EmailSourceError,
    EmailSourceFailureCategory,
)
from personal_edge_lab.infrastructure.gmail import oauth
from personal_edge_lab.infrastructure.gmail.oauth import (
    GMAIL_READONLY_SCOPE,
    GoogleOAuthCredentialStore,
    authorize_google_oauth,
)


def _token_document(*, expiry: datetime, refresh_token: str = "refresh-sentinel") -> dict[str, Any]:
    return {
        "token": "old-access-sentinel",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "client-secret-sentinel",
        "scopes": [GMAIL_READONLY_SCOPE],
        "expiry": expiry.isoformat().replace("+00:00", "Z"),
    }


def _write_token(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_valid_access_token_is_loaded_without_refresh(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    _write_token(token_file, _token_document(expiry=datetime.now(UTC) + timedelta(hours=1)))
    request_factory_called = False

    def request_factory() -> object:
        nonlocal request_factory_called
        request_factory_called = True
        return object()

    store = GoogleOAuthCredentialStore(
        token_file=token_file,
        timeout_seconds=10,
        request_factory=request_factory,
    )

    assert store.access_token() == "old-access-sentinel"
    assert not request_factory_called


def test_expired_token_is_refreshed_once_and_atomically_rewritten(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    _write_token(token_file, _token_document(expiry=datetime.now(UTC) - timedelta(hours=1)))
    calls: list[dict[str, Any]] = []

    class Response:
        status = 200
        data = b'{"access_token":"new-access-token","expires_in":3600,"token_type":"Bearer"}'
        headers: dict[str, str] = {}

    def request(**kwargs: Any) -> Response:
        calls.append(kwargs)
        return Response()

    store = GoogleOAuthCredentialStore(
        token_file=token_file,
        timeout_seconds=7,
        request_factory=lambda: request,
    )

    assert store.access_token() == "new-access-token"
    assert len(calls) == 1
    assert calls[0]["timeout"] == 7
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert json.loads(token_file.read_text())["token"] == "new-access-token"


def test_invalid_grant_is_sanitized_and_not_retried(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    sentinel = "refresh-secret-must-not-appear"
    _write_token(
        token_file,
        _token_document(
            expiry=datetime.now(UTC) - timedelta(hours=1),
            refresh_token=sentinel,
        ),
    )
    calls = 0

    class Response:
        status = 400
        data = b'{"error":"invalid_grant","error_description":"provider body sentinel"}'
        headers: dict[str, str] = {}

    def request(**_kwargs: Any) -> Response:
        nonlocal calls
        calls += 1
        return Response()

    store = GoogleOAuthCredentialStore(
        token_file=token_file,
        timeout_seconds=10,
        request_factory=lambda: request,
    )

    with pytest.raises(EmailSourceError) as caught:
        store.access_token()

    assert calls == 1
    assert caught.value.category is EmailSourceFailureCategory.AUTHENTICATION
    assert sentinel not in str(caught.value)
    assert "provider body" not in str(caught.value)


def test_missing_refresh_token_is_sanitized(tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    _write_token(
        token_file,
        _token_document(
            expiry=datetime.now(UTC) - timedelta(hours=1),
            refresh_token="",
        ),
    )
    store = GoogleOAuthCredentialStore(token_file=token_file, timeout_seconds=10)

    with pytest.raises(EmailSourceError) as caught:
        store.access_token()

    assert caught.value.category is EmailSourceFailureCategory.AUTHENTICATION


class _AuthorizedCredentials:
    def has_scopes(self, scopes: tuple[str, ...]) -> bool:
        return tuple(scopes) == (GMAIL_READONLY_SCOPE,)

    def to_json(self) -> str:
        return json.dumps(
            {
                "token": "new-token-sentinel",
                "refresh_token": "new-refresh-sentinel",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret-sentinel",
                "scopes": [GMAIL_READONLY_SCOPE],
            }
        )


def test_authorization_uses_fixed_loopback_and_readonly_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    captured: dict[str, Any] = {}

    class Flow:
        def run_local_server(self, **kwargs: Any) -> _AuthorizedCredentials:
            captured.update(kwargs)
            return _AuthorizedCredentials()

    class FlowFactory:
        @staticmethod
        def from_client_secrets_file(path: str, scopes: list[str]) -> Flow:
            captured["path"] = path
            captured["scopes"] = scopes
            return Flow()

    monkeypatch.setattr(oauth, "InstalledAppFlow", FlowFactory)

    authorize_google_oauth(
        client_secret_file=client_file,
        token_file=token_file,
        callback_port=8765,
        replace_token=False,
    )

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
    assert captured["open_browser"] is False
    assert captured["scopes"] == [GMAIL_READONLY_SCOPE]
    assert captured["access_type"] == "offline"
    assert captured["prompt"] == "consent"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_authorization_refuses_token_overwrite_without_explicit_flag(tmp_path: Path) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    token_file.write_text("existing-token-sentinel", encoding="utf-8")

    with pytest.raises(EmailSourceError) as caught:
        authorize_google_oauth(
            client_secret_file=client_file,
            token_file=token_file,
            callback_port=8765,
            replace_token=False,
        )

    assert caught.value.category is EmailSourceFailureCategory.AUTHENTICATION
    assert token_file.read_text() == "existing-token-sentinel"
