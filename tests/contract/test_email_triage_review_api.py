from __future__ import annotations

import sqlite3
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
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage_backfill import (
    SqliteTriageBackfillRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.email_triage.backfill import backfill_segments
from personal_edge_lab.modules.email_triage.input import prepare_triage_input

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
ORIGIN = "https://rubik-edge-01.local"
PASSWORD = "review-password!"
MESSAGE_ID = EmailMessageId("private-gmail-message-id")


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
        email_triage_workspace_enabled=enabled,
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


def _seed(database, document: EmailDocument) -> str:
    run_migrations(database)
    evidence, email = prepare_triage_input(document)
    with SqliteTriageRunRepository(database) as repository:
        repository.create_run(
            run_id="run-review",
            operation_id="operation-review",
            query_sha256="f" * 64,
            query_text="in:inbox private-query",
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
        stored = repository.store_message(
            run_id="run-review",
            ordinal=1,
            document=document,
            evidence=evidence,
            model_input=email.message,
            recorded_at=NOW,
        )
        reservation = repository.reserve(
            "run-review",
            ordinal=1,
            identity=_identity(document),
            operation_id="attempt-review",
            force_new_attempt=False,
            message_record_id=stored.database_id,
            content_snapshot_id=stored.content_snapshot_id,
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
            decision=TriageDecision(TriageLabel.JOB, "private reason sentinel"),
            completion=CompletionResult(
                text='{"label":"job","reason":"private reason sentinel"}',
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
    return stored.record_id


def _login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["email_triage_workspace_enabled"] is True
    assert response.json()["email_triage_review_enabled"] is True


def test_workspace_routes_are_authenticated_and_disabled_as_not_found(tmp_path) -> None:
    settings = _settings(tmp_path, enabled=False)
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        response = client.get("/api/v1/email-triage/messages")
        _login_disabled = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        disabled = client.get("/api/v1/email-triage/messages")

    assert response.status_code == 404
    assert disabled.status_code == 404
    assert disabled.headers["Cache-Control"] == "no-store"
    assert disabled.headers["Pragma"] == "no-cache"


def test_message_list_and_persisted_detail_need_no_gmail_call(tmp_path) -> None:
    settings = _settings(tmp_path)
    document = _document()
    record_id = _seed(settings.database_path, document)

    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        unauthorized = client.get("/api/v1/email-triage/messages")
        _login(client)
        listing = client.get(
            "/api/v1/email-triage/messages?limit=20&status=recommendations&label=job"
        )
        detail = client.get(f"/api/v1/email-triage/messages/{record_id}")

    assert unauthorized.status_code == 401
    assert listing.status_code == 200
    assert listing.headers["Cache-Control"] == "no-store"
    assert listing.json()["count"] == 1
    assert listing.json()["items"][0]["sender"] == document.sender
    assert listing.json()["items"][0]["subject"] == document.subject
    assert listing.json()["items"][0]["label"] == "job"
    assert listing.json()["items"][0]["reason_preview"] == "private reason sentinel"
    assert detail.status_code == 200
    assert detail.headers["Cache-Control"] == "no-store"
    assert detail.json()["normalized_text"] == document.text
    assert len(detail.json()["model_input"]) == 1600
    assert detail.json()["summary"]["label"] == "job"
    assert detail.json()["technical"]["trace_id"] == "4" * 32
    assert MESSAGE_ID.value not in detail.text
    assert "private-thread-id" not in detail.text


def test_message_filters_cursor_and_missing_detail_are_bounded(tmp_path) -> None:
    settings = _settings(tmp_path)
    record_id = _seed(settings.database_path, _document())
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        _login(client)
        empty = client.get("/api/v1/email-triage/messages?status=issues")
        bad_label = client.get("/api/v1/email-triage/messages?label=invalid")
        bad_cursor = client.get("/api/v1/email-triage/messages?cursor=not-a-cursor")
        missing = client.get("/api/v1/email-triage/messages/00000000000000000000000000000000")
        existing = client.get(f"/api/v1/email-triage/messages/{record_id}")

    assert empty.json()["items"] == []
    assert bad_label.status_code == 422
    assert bad_cursor.status_code == 422
    assert missing.status_code == 404
    assert existing.status_code == 200


def test_backfill_progress_is_protected_no_store_and_excludes_private_cursors(
    tmp_path,
) -> None:
    settings = _settings(tmp_path)
    run_migrations(settings.database_path)
    segments = backfill_segments(NOW)
    with SqliteTriageBackfillRepository(settings.database_path) as repository:
        repository.create_job(
            job_id="a" * 32,
            starts_at=segments[-1][0],
            ends_at=NOW,
            max_messages=5000,
            segments=segments,
            created_at=NOW,
        )

    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        unauthorized = client.get("/api/v1/email-triage/backfills")
        _login(client)
        listing = client.get("/api/v1/email-triage/backfills?limit=5")
        detail = client.get("/api/v1/email-triage/backfills/" + "a" * 32)

    assert unauthorized.status_code == 401
    assert listing.status_code == 200
    assert listing.headers["Cache-Control"] == "no-store"
    assert listing.json()["items"][0]["status"] == "ready"
    assert detail.status_code == 200
    assert detail.headers["Pragma"] == "no-cache"
    assert "page_cursor" not in detail.text
    assert "gmail_message_id" not in detail.text


def test_dashboard_feedback_is_csrf_protected_append_only_and_local_first(tmp_path) -> None:
    settings = replace(
        _settings(tmp_path),
        email_triage_feedback_enabled=True,
    )
    record_id = _seed(settings.database_path, _document())

    class UnavailablePublisher:
        def publish(self, _publication) -> None:
            raise RuntimeError("sentinel Langfuse provider body")

        def close(self) -> None:
            pass

    with TestClient(
        create_app(
            settings,
            triage_feedback_publisher_factory=UnavailablePublisher,
        ),
        base_url=ORIGIN,
    ) as client:
        login = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        csrf = login.json()["csrf_token"]
        missing_csrf = client.post(
            f"/api/v1/email-triage/messages/{record_id}/feedback",
            json={
                "recommendation_attempt_id": 1,
                "expected_version": 0,
                "action": "confirm",
                "corrected_label": None,
            },
        )
        headers = {
            "Origin": ORIGIN,
            "Sec-Fetch-Site": "same-origin",
            "X-CSRF-Token": csrf,
        }
        confirmed = client.post(
            f"/api/v1/email-triage/messages/{record_id}/feedback",
            headers=headers,
            json={
                "recommendation_attempt_id": 1,
                "expected_version": 0,
                "action": "confirm",
                "corrected_label": None,
            },
        )
        corrected = client.post(
            f"/api/v1/email-triage/messages/{record_id}/feedback",
            headers=headers,
            json={
                "recommendation_attempt_id": 1,
                "expected_version": 1,
                "action": "correct",
                "corrected_label": "admin",
            },
        )
        stale = client.post(
            f"/api/v1/email-triage/messages/{record_id}/feedback",
            headers=headers,
            json={
                "recommendation_attempt_id": 1,
                "expected_version": 0,
                "action": "dismiss",
                "corrected_label": None,
            },
        )
        detail = client.get(f"/api/v1/email-triage/messages/{record_id}")

    assert login.json()["email_triage_feedback_enabled"] is True
    assert missing_csrf.status_code == 403
    assert confirmed.status_code == 201
    assert confirmed.json()["action"] == "confirm"
    assert confirmed.json()["expected_label"] == "job"
    assert confirmed.json()["sync_status"] == "unavailable"
    assert "sentinel Langfuse provider body" not in confirmed.text
    assert corrected.status_code == 201
    assert corrected.json()["version"] == 2
    assert corrected.json()["expected_label"] == "admin"
    assert stale.status_code == 409
    assert detail.json()["summary"]["feedback_version"] == 2
    assert detail.json()["summary"]["latest_feedback"]["action"] == "correct"
    with SqliteTriageRunRepository(settings.database_path) as repository:
        publications = repository.pending_feedback_publications(limit=20)
    assert len(publications) == 2
    assert publications[-1].feedback.expected_label is TriageLabel.ADMIN
    assert publications[-1].trace_id == "4" * 32
    assert publications[-1].message_chars == 1600
    assert "Private Sender" not in repr(publications)
    assert "private-body" not in repr(publications)
    assert "private reason sentinel" not in repr(publications)
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_triage_feedback").fetchone() == (2,)
