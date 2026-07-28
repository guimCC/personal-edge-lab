from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from pwdlib import PasswordHash
from starlette.testclient import TestClient

from personal_edge_lab.apps.api.application import create_app
from personal_edge_lab.apps.api.config import Settings
from personal_edge_lab.domain.ai import CompletionResult, CompletionTiming, ModelIdentity
from personal_edge_lab.domain.email import (
    EmailContentSource,
    EmailDocument,
    EmailMessageId,
    EmailThreadId,
)
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriageDecision,
    TriageLabel,
    TriagePromptIdentity,
)
from personal_edge_lab.domain.email_triage_runs import (
    TriageEvaluationIdentity,
    TriageRunStatus,
)
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
ORIGIN = "https://rubik-edge-01.local"
PASSWORD = "review-password!"
MESSAGE_ID = EmailMessageId("private-gmail-message-id")


class _ExactSource:
    def __init__(self, document: EmailDocument) -> None:
        self.document = document
        self.calls = 0
        self.closed = False

    def retrieve_exact(self, message_id: EmailMessageId) -> EmailDocument:
        self.calls += 1
        assert message_id == MESSAGE_ID
        return self.document

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path, *, enabled: bool = True) -> Settings:
    password_hash = tmp_path / "owner-password.hash"
    password_hash.write_text(PasswordHash.recommended().hash(PASSWORD), encoding="utf-8")
    password_hash.chmod(0o600)
    return Settings(
        host="127.0.0.1",
        port=8000,
        telemetry_stale_after_seconds=45,
        docs_enabled=False,
        database_path=tmp_path / "telemetry.db",
        device_id="node-1",
        log_level=20,
        log_level_name="INFO",
        public_origin=ORIGIN,
        auth_enabled=True,
        password_hash_file=password_hash,
        gmail_triage_review_enabled=enabled,
    )


def _document(*, text: str = "private-body-" * 180) -> EmailDocument:
    return EmailDocument(
        message_id=MESSAGE_ID,
        thread_id=EmailThreadId("private-thread-id"),
        received_at=NOW,
        sender="Private Sender <sender@example.test>",
        subject="<script>Private subject</script>",
        text=text,
        content_source=EmailContentSource.PLAIN_TEXT,
        original_size_bytes=3000,
        normalized_char_count=len(text),
        truncated=False,
        metadata_truncated=False,
        quoted_text_removed=True,
        signature_removed=False,
        tracking_removed=False,
        duplicate_lines_removed=False,
    )


def _identity(document: EmailDocument) -> TriageEvaluationIdentity:
    from personal_edge_lab.modules.email_triage.input import prepare_triage_input

    evidence, _email = prepare_triage_input(document)
    return TriageEvaluationIdentity(
        identity_sha256="a" * 64,
        input=evidence,
        profile_name="email-triage",
        profile_version="1.0.0",
        taxonomy_version="1.0.0",
        schema_version="1.0.0",
        generation_parameters_version="1.0.0",
        prompt=TriagePromptIdentity(
            name="personal-edge-lab/email-triage",
            version="1",
            source=PromptSourceKind.LANGFUSE,
        ),
        model_alias="qwen3-1.7b-q4-k-m",
    )


def _seed(database, document: EmailDocument) -> None:
    run_migrations(database)
    with SqliteTriageRunRepository(database) as repository:
        repository.create_run(
            run_id="run-review",
            operation_id="operation-review",
            query_sha256="f" * 64,
            requested_limit=1,
            force_new_attempt=False,
            requested_at=NOW,
        )
        repository.mark_retrieving("run-review", updated_at=NOW)
        repository.record_retrieval(
            "run-review",
            document_count=1,
            failure_count=0,
            pages_fetched=1,
            api_call_count=2,
            elapsed_seconds=0.5,
            has_more=False,
            updated_at=NOW,
        )
        reservation = repository.reserve(
            "run-review",
            ordinal=1,
            identity=_identity(document),
            operation_id="attempt-review",
            force_new_attempt=False,
            reserved_at=NOW,
        )
        assert reservation.attempt_id is not None
        repository.mark_attempt_running(
            attempt_id=reservation.attempt_id,
            run_id="run-review",
            ordinal=1,
            started_at=NOW,
        )
        repository.complete_attempt(
            attempt_id=reservation.attempt_id,
            run_id="run-review",
            ordinal=1,
            decision=TriageDecision(TriageLabel.WORK, "private reason sentinel"),
            completion=CompletionResult(
                text='{"label":"work","reason":"private reason sentinel"}',
                identity=ModelIdentity("llama_cpp", "qwen3-1.7b-q4-k-m"),
                usage=None,
                timing=CompletionTiming(0.0, 1.0),
            ),
            trace_id="4" * 32,
            trace_unavailable=False,
            completed_at=NOW,
        )
        repository.complete_run(
            "run-review",
            status=TriageRunStatus.COMPLETED_WITH_RESULTS,
            completed_at=NOW,
        )


def _login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200


def test_review_routes_are_authenticated_and_disabled_as_not_found(tmp_path) -> None:
    settings = _settings(tmp_path, enabled=False)
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        response = client.get("/api/v1/email-triage/runs")
        _login(client)
        disabled = client.get("/api/v1/email-triage/runs")

    assert response.status_code == 404
    assert disabled.status_code == 404
    assert disabled.headers["Cache-Control"] == "no-store"
    assert disabled.headers["Pragma"] == "no-cache"


def test_review_list_detail_and_explicit_private_content_contract(tmp_path) -> None:
    settings = _settings(tmp_path)
    document = _document()
    _seed(settings.database_path, document)
    source = _ExactSource(document)
    with TestClient(
        create_app(settings, gmail_source_factory=lambda: source),
        base_url=ORIGIN,
    ) as client:
        unauthorized = client.get("/api/v1/email-triage/runs")
        _login(client)
        listing = client.get("/api/v1/email-triage/runs?limit=20&status=completed")
        detail = client.get("/api/v1/email-triage/runs/run-review")
        assert source.calls == 0
        content = client.get("/api/v1/email-triage/runs/run-review/items/1/review")

    assert unauthorized.status_code == 401
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert detail.status_code == 200
    detail_text = detail.text
    assert MESSAGE_ID.value not in detail_text
    assert "private-thread-id" not in detail_text
    assert "private reason sentinel" not in detail_text
    assert detail.json()["items"][0]["label"] == "work"
    assert detail.json()["items"][0]["reason_chars"] == 23
    assert content.status_code == 200
    assert content.headers["Cache-Control"] == "no-store"
    assert content.headers["Pragma"] == "no-cache"
    assert content.json()["sender"] == document.sender
    assert content.json()["subject"] == document.subject
    assert len(content.json()["model_input"]) == 1600
    assert content.json()["normalized_remainder"]
    assert content.json()["identity_verified"] is True
    assert source.calls == 1
    assert source.closed is True


def test_changed_message_content_is_sanitized_and_never_returned(tmp_path, caplog) -> None:
    settings = _settings(tmp_path)
    original = _document()
    _seed(settings.database_path, original)
    changed = replace(
        original,
        text="changed-private-body-sentinel",
        normalized_char_count=29,
    )
    with TestClient(
        create_app(settings, gmail_source_factory=lambda: _ExactSource(changed)),
        base_url=ORIGIN,
    ) as client:
        _login(client)
        response = client.get("/api/v1/email-triage/runs/run-review/items/1/review")

    assert response.status_code == 409
    assert response.json() == {"detail": "review content unavailable"}
    assert "changed-private-body-sentinel" not in response.text
    assert "changed-private-body-sentinel" not in caplog.text
    assert MESSAGE_ID.value not in caplog.text
