from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import httpx
import pytest

from personal_edge_lab.apps.email_triage_cli.__main__ import main
from personal_edge_lab.infrastructure.gmail.oauth import GMAIL_READONLY_SCOPE


def _private_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, enabled: bool = True) -> None:
    client = _private_json(
        tmp_path / "client.json",
        {
            "installed": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "client-secret-sentinel",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
    )
    token = _private_json(
        tmp_path / "token.json",
        {
            "token": "access-token-sentinel",
            "refresh_token": "refresh-token-sentinel",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id.apps.googleusercontent.com",
            "client_secret": "client-secret-sentinel",
            "scopes": [GMAIL_READONLY_SCOPE],
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        },
    )
    monkeypatch.setenv("GMAIL_READ_ENABLED", str(enabled).lower())
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(client))
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(token))


def _configure_triage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: bool = True,
) -> Path:
    _configure(monkeypatch, tmp_path)
    key = tmp_path / "unoq.key"
    key.write_text("u" * 64 + "\n", encoding="utf-8")
    key.chmod(0o600)
    database = tmp_path / "triage.db"
    monkeypatch.setenv("GMAIL_TRIAGE_ENABLED", str(enabled).lower())
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", str(key))
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://uno.local:8080")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("DATABASE_PATH", str(database))
    return database


def _message(*, body: str = "private-body-sentinel") -> dict[str, object]:
    return {
        "id": "message-id-1",
        "threadId": "thread-id-1",
        "internalDate": "1785141000000",
        "sizeEstimate": 1234,
        "payload": {
            "mimeType": "text/plain",
            "filename": "",
            "headers": [
                {"name": "From", "value": "Personal Sender <sender@example.test>"},
                {"name": "Subject", "value": "Personal subject"},
                {"name": "Content-Type", "value": "text/plain; charset=utf-8"},
            ],
            "body": {
                "data": base64.urlsafe_b64encode(body.encode()).decode().rstrip("="),
            },
        },
    }


def test_authorize_works_while_fetch_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, enabled=False)
    stdout = StringIO()
    captured: dict[str, object] = {}

    def runner(**kwargs: object) -> None:
        captured.update(kwargs)

    exit_code = main(
        ["authorize", "--replace-token"],
        stdout=stdout,
        stderr=StringIO(),
        authorization_runner=runner,
        operation_id_factory=lambda: "operation-1",
    )

    assert exit_code == 0
    assert captured["callback_port"] == 8765
    assert captured["replace_token"] is True
    assert "Authorization: success" in stdout.getvalue()
    assert "client-secret-sentinel" not in stdout.getvalue()


def test_disabled_fetch_performs_zero_http_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, enabled=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    stderr = StringIO()
    exit_code = main(
        ["fetch", "--query", "in:inbox"],
        stdout=StringIO(),
        stderr=stderr,
        transport=httpx.MockTransport(handler),
        operation_id_factory=lambda: "operation-2",
    )

    assert exit_code == 2
    assert calls == 0
    assert "GMAIL_READ_ENABLED" in stderr.getvalue()


def test_success_prints_metadata_but_never_body_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure(monkeypatch, tmp_path)
    query = "in:inbox private-query-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": "message-id-1", "threadId": "thread-id-1"}]},
            )
        return httpx.Response(200, json=_message())

    stdout = StringIO()
    with caplog.at_level(logging.INFO):
        exit_code = main(
            ["fetch", "--query", query, "--limit", "1"],
            stdout=stdout,
            stderr=StringIO(),
            transport=httpx.MockTransport(handler),
            operation_id_factory=lambda: "operation-3",
        )

    output = stdout.getvalue()
    logs = caplog.text
    assert exit_code == 0
    assert "Personal Sender <sender@example.test>" in output
    assert "Personal subject" in output
    assert "message-id-1" in output
    assert "private-body-sentinel" not in output
    assert "private-query-sentinel" not in logs
    for sentinel in (
        "private-body-sentinel",
        "access-token-sentinel",
        "refresh-token-sentinel",
        "client-secret-sentinel",
        "message-id-1",
        "sender@example.test",
        "Personal subject",
    ):
        assert sentinel not in logs
    assert "query_sha256=" in logs
    assert "api_call_count=2" in logs


def test_terminal_controls_in_metadata_are_replaced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": "message-id-1", "threadId": "thread-id-1"}]},
            )
        message = _message()
        message["payload"]["headers"][1]["value"] = "Subject\x1b[31m"  # type: ignore[index]
        return httpx.Response(200, json=message)

    stdout = StringIO()
    exit_code = main(
        ["fetch", "--query", "in:inbox", "--limit", "1"],
        stdout=stdout,
        stderr=StringIO(),
        transport=httpx.MockTransport(handler),
    )

    assert exit_code == 0
    assert "\x1b" not in stdout.getvalue()
    assert "Subject�[31m" in stdout.getvalue()


def test_partial_message_failure_prints_category_and_exits_five(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": "message-id-1", "threadId": "thread-id-1"}]},
            )
        message = _message()
        message["payload"]["body"] = {"data": "%%%"}  # type: ignore[index]
        return httpx.Response(200, json=message)

    stdout = StringIO()
    exit_code = main(
        ["fetch", "--query", "in:inbox", "--limit", "1"],
        stdout=stdout,
        stderr=StringIO(),
        transport=httpx.MockTransport(handler),
    )

    assert exit_code == 5
    assert "Failures: 1" in stdout.getvalue()
    assert "Message failure: invalid_message" in stdout.getvalue()


@pytest.mark.parametrize(
    ("response_or_error", "exit_code", "category"),
    [
        (httpx.ConnectError("connection secret"), 3, "connection"),
        (httpx.ReadTimeout("timeout secret"), 4, "timeout"),
        (httpx.Response(401, text="provider-body-sentinel"), 5, "authentication"),
        (httpx.Response(429, text="provider-body-sentinel"), 5, "rate_limited"),
        (httpx.Response(503, text="provider-body-sentinel"), 5, "source_unavailable"),
    ],
)
def test_failure_exit_codes_and_output_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response_or_error: httpx.Response | httpx.RequestError,
    exit_code: int,
    category: str,
) -> None:
    _configure(monkeypatch, tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(response_or_error, httpx.RequestError):
            raise response_or_error
        return response_or_error

    stderr = StringIO()
    actual = main(
        ["fetch", "--query", "in:inbox"],
        stdout=StringIO(),
        stderr=stderr,
        transport=httpx.MockTransport(handler),
    )

    assert actual == exit_code
    assert category in stderr.getvalue()
    assert "secret" not in stderr.getvalue()
    assert "provider-body-sentinel" not in stderr.getvalue()


@pytest.mark.parametrize(("query", "limit"), [("", "1"), ("in:inbox", "0"), ("x" * 513, "1")])
def test_invalid_input_exits_two_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    query: str,
    limit: str,
) -> None:
    _configure(monkeypatch, tmp_path)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    exit_code = main(
        ["fetch", "--query", query, "--limit", limit],
        stdout=StringIO(),
        stderr=StringIO(),
        transport=httpx.MockTransport(handler),
    )

    assert exit_code == 2
    assert calls == 0


def test_disabled_mailbox_triage_performs_zero_http_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_triage(monkeypatch, tmp_path, enabled=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    stderr = StringIO()
    exit_code = main(
        ["triage", "--query", "in:inbox", "--limit", "1"],
        stdout=StringIO(),
        stderr=stderr,
        transport=httpx.MockTransport(handler),
    )

    assert exit_code == 2
    assert calls == 0
    assert "GMAIL_TRIAGE_ENABLED" in stderr.getvalue()


def test_mailbox_triage_persists_product_content_but_keeps_logs_private_and_reuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = _configure_triage(monkeypatch, tmp_path)
    model_calls = 0
    query = "in:inbox private-query-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": "message-id-1", "threadId": "thread-id-1"}]},
            )
        if request.url.path.startswith("/gmail/"):
            return httpx.Response(200, json=_message())
        model_calls += 1
        return httpx.Response(
            200,
            json={
                "model": "/private/model/path.gguf",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": ('{"label":"billing","reason":"private-reason-sentinel"}'),
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    caplog.set_level(logging.INFO)
    first_out = StringIO()
    first = main(
        ["triage", "--query", query, "--limit", "1"],
        stdout=first_out,
        stderr=StringIO(),
        transport=httpx.MockTransport(handler),
        operation_id_factory=lambda: "run-one",
    )
    second_out = StringIO()
    second = main(
        ["triage", "--query", query, "--limit", "1"],
        stdout=second_out,
        stderr=StringIO(),
        transport=httpx.MockTransport(handler),
        operation_id_factory=lambda: "run-two",
    )

    assert first == second == 0
    assert model_calls == 1
    assert "Proposed label: billing" in first_out.getvalue()
    assert "Reason: private-reason-sentinel" in first_out.getvalue()
    assert "Item 1: reused" in second_out.getvalue()
    assert "Reason: intentionally not retained" in second_out.getvalue()
    assert "Gmail changes: none" in first_out.getvalue()
    persisted = database.read_bytes()
    for sentinel in (
        b"private-query-sentinel",
        b"sender@example.test",
        b"private-body-sentinel",
        b"private-reason-sentinel",
    ):
        assert sentinel in persisted
        assert sentinel.decode() not in caplog.text
    assert b"/private/model/path.gguf" not in persisted
    assert "/private/model/path.gguf" not in caplog.text

    monkeypatch.setenv("GMAIL_TRIAGE_ENABLED", "false")
    monkeypatch.setenv("GMAIL_READ_ENABLED", "false")
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    history = StringIO()
    assert (
        main(
            ["runs"],
            stdout=history,
            stderr=StringIO(),
            operation_id_factory=lambda: "history-operation",
        )
        == 0
    )
    assert "run-one" in history.getvalue()
    details = StringIO()
    assert (
        main(
            ["show", "--run-id", "run-one"],
            stdout=details,
            stderr=StringIO(),
            operation_id_factory=lambda: "show-operation",
        )
        == 0
    )
    assert "Label: billing" in details.getvalue()
    assert "private-reason-sentinel" not in details.getvalue()


def test_mailbox_triage_limit_is_rejected_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_triage(monkeypatch, tmp_path)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    assert (
        main(
            ["triage", "--query", "in:inbox", "--limit", "11"],
            stdout=StringIO(),
            stderr=StringIO(),
            transport=httpx.MockTransport(handler),
        )
        == 2
    )
    assert calls == 0


def test_development_reset_cli_requires_exact_confirmation_and_reports_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "telemetry.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    refused = StringIO()
    assert (
        main(
            ["reset-development-data", "--confirm", "yes"],
            stdout=StringIO(),
            stderr=refused,
            operation_id_factory=lambda: "reset-refused",
        )
        == 2
    )
    assert "exact reset confirmation" in refused.getvalue()

    output = StringIO()
    assert (
        main(
            [
                "reset-development-data",
                "--confirm",
                "DELETE-ALL-EMAIL-TRIAGE-DATA",
            ],
            stdout=output,
            stderr=StringIO(),
            operation_id_factory=lambda: "reset-success",
        )
        == 0
    )
    assert "Deleted email-triage rows: 0" in output.getvalue()
    assert "Other application data: preserved" in output.getvalue()
    assert list((tmp_path / "backups").glob("telemetry-triage-reset-*.db"))
