from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from personal_edge_lab.domain.ai import CompletionResult, CompletionTiming, ModelIdentity
from personal_edge_lab.domain.email import (
    EmailContentSource,
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
    TriageInputEvidence,
    TriageReservationStatus,
    TriageRunItemStatus,
    TriageRunStatus,
)
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _identity(*, suffix: str = "a") -> TriageEvaluationIdentity:
    return TriageEvaluationIdentity(
        identity_sha256=suffix * 64,
        input=TriageInputEvidence(
            message_id=EmailMessageId(f"message-{suffix}"),
            thread_id=EmailThreadId(f"thread-{suffix}"),
            received_at=NOW,
            message_fingerprint="1" * 64,
            normalized_sha256="2" * 64,
            model_input_sha256="3" * 64,
            sender_chars=20,
            subject_chars=7,
            normalized_chars=30,
            model_message_chars=30,
            original_size_bytes=123,
            content_source=EmailContentSource.PLAIN_TEXT,
            source_truncated=False,
            model_input_truncated=False,
            metadata_truncated=False,
            cleanup_flags=("tracking_removed",),
        ),
        profile_name="email-triage",
        profile_version="1.0.0",
        taxonomy_version="1.0.0",
        schema_version="1.0.0",
        generation_parameters_version="1.0.0",
        prompt=TriagePromptIdentity(
            name="personal-edge-lab/email-triage",
            version="7",
            source=PromptSourceKind.LANGFUSE,
        ),
        model_alias="qwen3-1.7b-q4-k-m",
    )


def _create_run(repository, run_id: str, *, force: bool = False, at: datetime = NOW) -> None:
    repository.create_run(
        run_id=run_id,
        operation_id=f"operation-{run_id}",
        query_sha256="f" * 64,
        requested_limit=1,
        force_new_attempt=force,
        requested_at=at,
    )
    repository.mark_retrieving(run_id, updated_at=at)
    repository.record_retrieval(
        run_id,
        document_count=1,
        failure_count=0,
        pages_fetched=1,
        api_call_count=2,
        elapsed_seconds=0.5,
        has_more=False,
        updated_at=at,
    )


def _complete(repository, run_id: str, attempt_id: int) -> None:
    repository.mark_attempt_running(
        attempt_id=attempt_id,
        run_id=run_id,
        ordinal=1,
        started_at=NOW,
    )
    repository.complete_attempt(
        attempt_id=attempt_id,
        run_id=run_id,
        ordinal=1,
        decision=TriageDecision(TriageLabel.BILLING, "private-reason-sentinel"),
        completion=CompletionResult(
            text='{"label":"billing","reason":"private-reason-sentinel"}',
            identity=ModelIdentity("llama_cpp", "qwen3-1.7b-q4-k-m"),
            usage=None,
            timing=CompletionTiming(0.1, 1.2),
        ),
        trace_id="4" * 32,
        trace_unavailable=False,
        completed_at=NOW,
    )


def test_success_is_reused_and_forced_attempt_remains_auditable(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageRunRepository(database) as repository:
        _create_run(repository, "run-one")
        first = repository.reserve(
            "run-one",
            ordinal=1,
            identity=_identity(),
            operation_id="attempt-one",
            force_new_attempt=False,
            reserved_at=NOW,
        )
        assert first.status is TriageReservationStatus.NEW
        assert first.attempt_id is not None
        _complete(repository, "run-one", first.attempt_id)
        repository.complete_run(
            "run-one",
            status=TriageRunStatus.COMPLETED_WITH_RESULTS,
            completed_at=NOW,
        )

        _create_run(repository, "run-two")
        replay = repository.reserve(
            "run-two",
            ordinal=1,
            identity=_identity(),
            operation_id="attempt-two",
            force_new_attempt=False,
            reserved_at=NOW,
        )
        assert replay.status is TriageReservationStatus.REUSED
        assert replay.decision is not None
        assert replay.decision.label is TriageLabel.BILLING

        _create_run(repository, "run-three", force=True)
        forced = repository.reserve(
            "run-three",
            ordinal=1,
            identity=_identity(),
            operation_id="attempt-three",
            force_new_attempt=True,
            reserved_at=NOW,
        )
        assert forced.status is TriageReservationStatus.NEW
        assert forced.attempt_id != first.attempt_id

    with sqlite3.connect(database) as connection:
        attempts = connection.execute(
            "SELECT attempt_number, status FROM email_triage_attempts ORDER BY id"
        ).fetchall()
    assert attempts == [(1, "succeeded"), (2, "reserved")]


def test_active_evaluation_is_not_called_twice(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageRunRepository(database) as repository:
        _create_run(repository, "run-one")
        first = repository.reserve(
            "run-one",
            ordinal=1,
            identity=_identity(),
            operation_id="attempt-one",
            force_new_attempt=False,
            reserved_at=NOW,
        )
        _create_run(repository, "run-two")
        concurrent = repository.reserve(
            "run-two",
            ordinal=1,
            identity=_identity(),
            operation_id="attempt-two",
            force_new_attempt=True,
            reserved_at=NOW,
        )
        assert first.status is TriageReservationStatus.NEW
        assert concurrent.status is TriageReservationStatus.CONCURRENT
        assert concurrent.attempt_id == first.attempt_id
        details = repository.get("run-two")
        assert details is not None
        assert details.items[0].status is TriageRunItemStatus.FAILED
        assert details.items[0].failure_category == "concurrent_evaluation"


def test_stale_unknown_work_is_explicitly_interrupted(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    stale = NOW - timedelta(minutes=10)
    with SqliteTriageRunRepository(database) as repository:
        _create_run(repository, "stale-run", at=stale)
        reservation = repository.reserve(
            "stale-run",
            ordinal=1,
            identity=_identity(),
            operation_id="stale-attempt",
            force_new_attempt=False,
            reserved_at=stale,
        )
        assert reservation.attempt_id is not None
        repository.mark_attempt_running(
            attempt_id=reservation.attempt_id,
            run_id="stale-run",
            ordinal=1,
            started_at=stale,
        )
        recovered = repository.recover_stale(
            stale_before=NOW - timedelta(minutes=5),
            recovered_at=NOW,
        )
        assert recovered == 1
        details = repository.get("stale-run")
        assert details is not None
        assert details.run.status is TriageRunStatus.INTERRUPTED
        assert details.items[0].status is TriageRunItemStatus.INTERRUPTED


def test_repository_never_stores_query_or_email_content(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageRunRepository(database) as repository:
        _create_run(repository, "privacy-run")
        reservation = repository.reserve(
            "privacy-run",
            ordinal=1,
            identity=_identity(),
            operation_id="privacy-attempt",
            force_new_attempt=False,
            reserved_at=NOW,
        )
        assert reservation.attempt_id is not None
        _complete(repository, "privacy-run", reservation.attempt_id)

    raw_database = database.read_bytes()
    for sentinel in (
        b"private-query-sentinel",
        b"sender@example.test",
        b"private-body-sentinel",
        b"private-reason-sentinel",
    ):
        assert sentinel not in raw_database
