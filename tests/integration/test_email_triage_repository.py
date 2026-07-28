from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

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
from personal_edge_lab.domain.email_triage_messages import TriageMessageFilter
from personal_edge_lab.domain.email_triage_review import TriageRunFilter
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
from personal_edge_lab.modules.email_triage.input import prepare_triage_input

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


def test_repository_stores_decision_reason_but_not_unprovided_email_content(tmp_path) -> None:
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
    ):
        assert sentinel not in raw_database
    assert b"private-reason-sentinel" in raw_database


def test_review_queries_expose_decision_evidence_but_keep_gmail_id_internal(
    tmp_path,
) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageRunRepository(database) as repository:
        _create_run(repository, "review-run")
        reservation = repository.reserve(
            "review-run",
            ordinal=1,
            identity=_identity(),
            operation_id="review-attempt",
            force_new_attempt=False,
            reserved_at=NOW,
        )
        assert reservation.attempt_id is not None
        _complete(repository, "review-run", reservation.attempt_id)
        repository.complete_run(
            "review-run",
            status=TriageRunStatus.COMPLETED_WITH_RESULTS,
            completed_at=NOW,
        )

        completed = repository.review_recent(
            limit=20,
            run_filter=TriageRunFilter.COMPLETED,
        )
        issues = repository.review_recent(limit=20, run_filter=TriageRunFilter.ISSUES)
        detail = repository.get("review-run")
        reference = repository.review_reference("review-run", 1)

    assert [run.run_id for run in completed] == ["review-run"]
    assert issues == []
    assert detail is not None
    assert detail.items[0].decision_sha256 is not None
    assert detail.items[0].reason_chars == len("private-reason-sentinel")
    assert not hasattr(detail.items[0], "message_id")
    assert reference is not None
    assert reference.message_id == EmailMessageId("message-a")


def test_message_projection_deduplicates_and_preserves_success_after_later_failure(
    tmp_path,
) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    document = EmailDocument(
        message_id=EmailMessageId("message-product"),
        thread_id=EmailThreadId("thread-product"),
        received_at=NOW,
        sender="Product Sender <product@example.test>",
        subject="Product subject",
        text="product body sentinel",
        content_source=EmailContentSource.PLAIN_TEXT,
        original_size_bytes=21,
        normalized_char_count=21,
        truncated=False,
        metadata_truncated=False,
        quoted_text_removed=False,
        signature_removed=False,
        tracking_removed=False,
        duplicate_lines_removed=False,
    )
    evidence, email = prepare_triage_input(document)
    identity = TriageEvaluationIdentity(
        identity_sha256="9" * 64,
        input=evidence,
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
    with SqliteTriageRunRepository(database) as repository:
        _create_run(repository, "product-one")
        first_stored = repository.store_message(
            run_id="product-one",
            ordinal=1,
            document=document,
            evidence=evidence,
            model_input=email.message,
            recorded_at=NOW,
        )
        first = repository.reserve(
            "product-one",
            ordinal=1,
            identity=identity,
            operation_id="product-first-attempt",
            force_new_attempt=False,
            message_record_id=first_stored.database_id,
            content_snapshot_id=first_stored.content_snapshot_id,
            reserved_at=NOW,
        )
        assert first.attempt_id is not None
        _complete(repository, "product-one", first.attempt_id)
        repository.complete_run(
            "product-one",
            status=TriageRunStatus.COMPLETED_WITH_RESULTS,
            completed_at=NOW,
        )

        later = NOW + timedelta(seconds=1)
        _create_run(repository, "product-two", force=True, at=later)
        second_stored = repository.store_message(
            run_id="product-two",
            ordinal=1,
            document=document,
            evidence=evidence,
            model_input=email.message,
            recorded_at=later,
        )
        second = repository.reserve(
            "product-two",
            ordinal=1,
            identity=identity,
            operation_id="product-second-attempt",
            force_new_attempt=True,
            message_record_id=second_stored.database_id,
            content_snapshot_id=second_stored.content_snapshot_id,
            reserved_at=later,
        )
        assert second.attempt_id is not None
        repository.fail_attempt(
            attempt_id=second.attempt_id,
            run_id="product-two",
            ordinal=1,
            category="timeout",
            provider="llama_cpp",
            model_alias="qwen3-1.7b-q4-k-m",
            queue_wait_seconds=0,
            provider_seconds=60,
            attempt_count=1,
            retry_eligible=True,
            retry_after_seconds=None,
            trace_id=None,
            trace_unavailable=True,
            completed_at=later,
        )

        page = repository.message_page(
            limit=20,
            message_filter=TriageMessageFilter.ISSUES,
            label=None,
            cursor=None,
        )
        recommendations = repository.message_page(
            limit=20,
            message_filter=TriageMessageFilter.RECOMMENDATIONS,
            label=None,
            cursor=None,
        )
        assert len(page.items) == 1
        assert len(recommendations.items) == 1
        assert page.items[0].latest_status is TriageRunItemStatus.FAILED
        assert page.items[0].latest_failure_category == "timeout"
        assert page.items[0].label is TriageLabel.BILLING
        assert page.items[0].reason == "private-reason-sentinel"
        assert first_stored.record_id == second_stored.record_id
        detail = repository.message_detail(first_stored.record_id)
        assert detail is not None
        assert detail.normalized_text == "product body sentinel"
        assert detail.technical.attempt_id == first.attempt_id
        assert detail.technical.run_id == "product-one"
