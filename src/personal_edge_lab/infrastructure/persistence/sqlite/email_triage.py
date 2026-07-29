"""SQLite evidence repository for durable read-only mailbox triage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from personal_edge_lab.domain.ai import CompletionResult
from personal_edge_lab.domain.email import (
    EmailContentSource,
    EmailDocument,
    EmailItemFailure,
    EmailMessageId,
)
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriageDecision,
    TriageDecisionSource,
    TriageLabel,
)
from personal_edge_lab.domain.email_triage_messages import (
    StoredTriageMessage,
    TriageMessageCursor,
    TriageMessageDetail,
    TriageMessageFilter,
    TriageMessagePage,
    TriageMessageSummary,
    TriageMessageTechnicalEvidence,
    validate_message_limit,
)
from personal_edge_lab.domain.email_triage_review import (
    TriageReviewReference,
    TriageRunFilter,
)
from personal_edge_lab.domain.email_triage_runs import (
    StoredTriageDecision,
    TriageEvaluationIdentity,
    TriageInputEvidence,
    TriageReservation,
    TriageReservationStatus,
    TriageRunDetails,
    TriageRunItemStatus,
    TriageRunItemSummary,
    TriageRunStatus,
    TriageRunSummary,
    validate_recent_run_limit,
)
from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection


class SqliteTriageRunRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._database_path = database_path
        self._connection = open_connection(database_path, timeout_seconds=timeout_seconds)

    def __enter__(self) -> SqliteTriageRunRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def recover_stale(self, *, stale_before: datetime, recovered_at: datetime) -> int:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            run_rows = self._connection.execute(
                """
                SELECT run_id FROM email_triage_runs
                WHERE status IN ('requested', 'retrieving', 'classifying')
                  AND updated_at_utc < ?
                """,
                (stale_before.isoformat(),),
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in run_rows]
            for run_id in run_ids:
                self._connection.execute(
                    """
                    UPDATE email_triage_attempts
                    SET status = 'interrupted', completed_at_utc = ?,
                        failure_category = 'interrupted'
                    WHERE run_id = ? AND status IN ('reserved', 'running')
                    """,
                    (recovered_at.isoformat(), run_id),
                )
                self._connection.execute(
                    """
                    UPDATE email_triage_run_items
                    SET status = 'interrupted', completed_at_utc = ?,
                        failure_category = 'interrupted'
                    WHERE run_id = ? AND status IN ('pending', 'classifying')
                    """,
                    (recovered_at.isoformat(), run_id),
                )
                self._connection.execute(
                    """
                    UPDATE email_triage_messages
                    SET latest_status = 'interrupted',
                        latest_failure_category = 'interrupted',
                        last_seen_at_utc = ?
                    WHERE latest_run_id = ?
                      AND latest_status IN ('pending', 'classifying')
                    """,
                    (recovered_at.isoformat(), run_id),
                )
                self._connection.execute(
                    """
                    UPDATE email_triage_runs
                    SET status = 'interrupted', updated_at_utc = ?,
                        completed_at_utc = ?, failure_category = 'interrupted'
                    WHERE run_id = ?
                    """,
                    (recovered_at.isoformat(), recovered_at.isoformat(), run_id),
                )
            self._connection.commit()
            return len(run_ids)
        except BaseException:
            self._connection.rollback()
            raise

    def create_run(
        self,
        *,
        run_id: str,
        operation_id: str,
        query_sha256: str,
        requested_limit: int,
        force_new_attempt: bool,
        requested_at: datetime,
        query_text: str = "",
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO email_triage_runs (
                run_id, operation_id, query_sha256, query_text, requested_limit,
                force_new_attempt, status, requested_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 'requested', ?, ?)
            """,
            (
                run_id,
                operation_id,
                query_sha256,
                query_text,
                requested_limit,
                int(force_new_attempt),
                requested_at.isoformat(),
                requested_at.isoformat(),
            ),
        )
        self._connection.commit()

    def mark_retrieving(self, run_id: str, *, updated_at: datetime) -> None:
        self._update_run_state(run_id, TriageRunStatus.RETRIEVING, updated_at)

    def record_retrieval(
        self,
        run_id: str,
        *,
        document_count: int,
        failure_count: int,
        pages_fetched: int,
        api_call_count: int,
        elapsed_seconds: float,
        has_more: bool,
        updated_at: datetime,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_runs
            SET status = 'classifying', document_count = ?,
                retrieval_failure_count = ?, pages_fetched = ?,
                api_call_count = ?, retrieval_seconds = ?, has_more = ?,
                updated_at_utc = ?
            WHERE run_id = ?
            """,
            (
                document_count,
                failure_count,
                pages_fetched,
                api_call_count,
                elapsed_seconds,
                int(has_more),
                updated_at.isoformat(),
                run_id,
            ),
        )
        _require_one(cursor, "triage run")
        self._connection.commit()

    def fail_before_items(
        self,
        run_id: str,
        *,
        category: str,
        completed_at: datetime,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_runs
            SET status = 'failed_before_items', failure_category = ?,
                updated_at_utc = ?, completed_at_utc = ?
            WHERE run_id = ?
            """,
            (category, completed_at.isoformat(), completed_at.isoformat(), run_id),
        )
        _require_one(cursor, "triage run")
        self._connection.commit()

    def record_source_failure(
        self,
        run_id: str,
        *,
        ordinal: int,
        failure: EmailItemFailure,
        recorded_at: datetime,
    ) -> None:
        message_id = failure.message_id.value if failure.message_id is not None else None
        fingerprint_source = message_id or f"{run_id}:source-failure:{ordinal}"
        self.record_item_failure(
            run_id,
            ordinal=ordinal,
            message_id=message_id,
            message_fingerprint=_sha256(fingerprint_source),
            received_at=None,
            message_record_id=None,
            category=failure.category.value,
            recorded_at=recorded_at,
        )

    def store_message(
        self,
        *,
        run_id: str,
        ordinal: int,
        document: EmailDocument,
        evidence: TriageInputEvidence,
        model_input: str,
        recorded_at: datetime,
    ) -> StoredTriageMessage:
        record_id = _sha256(f"email-triage-message:{document.message_id.value}")[:32]
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                INSERT INTO email_triage_messages (
                    record_id, gmail_message_id, gmail_thread_id, received_at_utc,
                    latest_run_id, latest_item_ordinal, latest_status,
                    first_seen_at_utc, last_seen_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(gmail_message_id) DO UPDATE SET
                    gmail_thread_id = excluded.gmail_thread_id,
                    received_at_utc = excluded.received_at_utc,
                    latest_run_id = excluded.latest_run_id,
                    latest_item_ordinal = excluded.latest_item_ordinal,
                    latest_status = 'pending',
                    latest_failure_category = NULL,
                    last_seen_at_utc = excluded.last_seen_at_utc
                """,
                (
                    record_id,
                    document.message_id.value,
                    document.thread_id.value,
                    document.received_at.isoformat(),
                    run_id,
                    ordinal,
                    recorded_at.isoformat(),
                    recorded_at.isoformat(),
                ),
            )
            message_row = self._connection.execute(
                "SELECT id, record_id FROM email_triage_messages WHERE gmail_message_id = ?",
                (document.message_id.value,),
            ).fetchone()
            if message_row is None:
                raise sqlite3.DatabaseError("triage message storage failed")
            message_record_id = int(message_row["id"])
            self._connection.execute(
                """
                INSERT INTO email_triage_content_snapshots (
                    message_record_id, sender, subject, normalized_text, model_input,
                    normalized_sha256, model_input_sha256, original_size_bytes,
                    content_source, cleanup_flags_json, source_truncated,
                    model_input_truncated, metadata_truncated, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_record_id, normalized_sha256, model_input_sha256)
                DO NOTHING
                """,
                (
                    message_record_id,
                    document.sender,
                    document.subject,
                    document.text,
                    model_input,
                    evidence.normalized_sha256,
                    evidence.model_input_sha256,
                    document.original_size_bytes,
                    document.content_source.value,
                    json.dumps(evidence.cleanup_flags, separators=(",", ":")),
                    int(document.truncated),
                    int(evidence.model_input_truncated),
                    int(document.metadata_truncated),
                    recorded_at.isoformat(),
                ),
            )
            snapshot_row = self._connection.execute(
                """
                SELECT id FROM email_triage_content_snapshots
                WHERE message_record_id = ?
                  AND normalized_sha256 = ?
                  AND model_input_sha256 = ?
                """,
                (
                    message_record_id,
                    evidence.normalized_sha256,
                    evidence.model_input_sha256,
                ),
            ).fetchone()
            if snapshot_row is None:
                raise sqlite3.DatabaseError("triage content storage failed")
            snapshot_id = int(snapshot_row["id"])
            self._connection.execute(
                "UPDATE email_triage_messages SET current_content_snapshot_id = ? WHERE id = ?",
                (snapshot_id, message_record_id),
            )
            self._connection.commit()
            return StoredTriageMessage(
                database_id=message_record_id,
                record_id=str(message_row["record_id"]),
                content_snapshot_id=snapshot_id,
            )
        except BaseException:
            self._connection.rollback()
            raise

    def reserve(
        self,
        run_id: str,
        *,
        ordinal: int,
        identity: TriageEvaluationIdentity,
        operation_id: str,
        force_new_attempt: bool,
        reserved_at: datetime,
        message_record_id: int | None = None,
        content_snapshot_id: int | None = None,
    ) -> TriageReservation:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._insert_evaluation(identity, reserved_at)
            evaluation = self._connection.execute(
                """
                SELECT id FROM email_triage_evaluations
                WHERE identity_sha256 = ?
                """,
                (identity.identity_sha256,),
            ).fetchone()
            if evaluation is None:
                raise sqlite3.DatabaseError("triage evaluation reservation failed")
            evaluation_id = int(evaluation["id"])
            if content_snapshot_id is not None:
                self._connection.execute(
                    """
                    INSERT INTO email_triage_evaluation_content (
                        evaluation_id, content_snapshot_id
                    ) VALUES (?, ?)
                    ON CONFLICT(evaluation_id) DO NOTHING
                    """,
                    (evaluation_id, content_snapshot_id),
                )
            self._connection.execute(
                """
                INSERT INTO email_triage_run_items (
                    run_id, ordinal, gmail_message_id, message_fingerprint,
                    received_at_utc, evaluation_id, message_record_id,
                    status, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    run_id,
                    ordinal,
                    identity.input.message_id.value,
                    identity.input.message_fingerprint,
                    identity.input.received_at.isoformat(),
                    evaluation_id,
                    message_record_id,
                    reserved_at.isoformat(),
                ),
            )

            active = self._connection.execute(
                """
                SELECT id FROM email_triage_attempts
                WHERE evaluation_id = ? AND status IN ('reserved', 'running')
                ORDER BY id DESC LIMIT 1
                """,
                (evaluation_id,),
            ).fetchone()
            if active is not None:
                attempt_id = int(active["id"])
                self._set_item(
                    run_id,
                    ordinal,
                    status=TriageRunItemStatus.FAILED,
                    attempt_id=attempt_id,
                    failure_category="concurrent_evaluation",
                    completed_at=reserved_at,
                )
                if message_record_id is not None:
                    self._set_message_processing(
                        message_record_id,
                        run_id=run_id,
                        ordinal=ordinal,
                        status=TriageRunItemStatus.FAILED,
                        failure_category="concurrent_evaluation",
                        successful_attempt_id=None,
                        seen_at=reserved_at,
                    )
                self._connection.commit()
                return TriageReservation(
                    TriageReservationStatus.CONCURRENT,
                    evaluation_id=evaluation_id,
                    attempt_id=attempt_id,
                )

            succeeded = self._connection.execute(
                """
                SELECT id, label, decision_sha256, reason_chars, trace_id,
                    decision_source, rule_id, rule_version
                FROM email_triage_attempts
                WHERE evaluation_id = ? AND status = 'succeeded'
                ORDER BY id DESC LIMIT 1
                """,
                (evaluation_id,),
            ).fetchone()
            if succeeded is not None and not force_new_attempt:
                attempt_id = int(succeeded["id"])
                decision = StoredTriageDecision(
                    label=TriageLabel(str(succeeded["label"])),
                    decision_sha256=str(succeeded["decision_sha256"]),
                    reason_chars=(
                        int(succeeded["reason_chars"])
                        if succeeded["reason_chars"] is not None
                        else None
                    ),
                    source=TriageDecisionSource(str(succeeded["decision_source"])),
                    rule_id=(
                        str(succeeded["rule_id"]) if succeeded["rule_id"] is not None else None
                    ),
                    rule_version=(
                        str(succeeded["rule_version"])
                        if succeeded["rule_version"] is not None
                        else None
                    ),
                )
                self._set_item(
                    run_id,
                    ordinal,
                    status=TriageRunItemStatus.REUSED,
                    attempt_id=attempt_id,
                    failure_category=None,
                    completed_at=reserved_at,
                )
                if message_record_id is not None:
                    self._set_message_processing(
                        message_record_id,
                        run_id=run_id,
                        ordinal=ordinal,
                        status=TriageRunItemStatus.REUSED,
                        failure_category=None,
                        successful_attempt_id=attempt_id,
                        seen_at=reserved_at,
                    )
                self._connection.commit()
                return TriageReservation(
                    TriageReservationStatus.REUSED,
                    evaluation_id=evaluation_id,
                    attempt_id=attempt_id,
                    decision=decision,
                    trace_id=(
                        str(succeeded["trace_id"]) if succeeded["trace_id"] is not None else None
                    ),
                )

            next_number = int(
                self._connection.execute(
                    """
                    SELECT COALESCE(MAX(attempt_number), 0) + 1
                    FROM email_triage_attempts WHERE evaluation_id = ?
                    """,
                    (evaluation_id,),
                ).fetchone()[0]
            )
            cursor = self._connection.execute(
                """
                INSERT INTO email_triage_attempts (
                    evaluation_id, run_id, item_ordinal, operation_id,
                    attempt_number, status, reserved_at_utc, provider_attempt_count,
                    decision_source, rule_id, rule_version
                ) VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    run_id,
                    ordinal,
                    operation_id,
                    next_number,
                    reserved_at.isoformat(),
                    0 if identity.decision_source is TriageDecisionSource.RULE else 1,
                    identity.decision_source.value,
                    identity.rule_id,
                    identity.rule_version,
                ),
            )
            attempt_id = _lastrowid(cursor)
            self._set_item(
                run_id,
                ordinal,
                status=TriageRunItemStatus.CLASSIFYING,
                attempt_id=attempt_id,
                failure_category=None,
                completed_at=None,
            )
            if message_record_id is not None:
                self._set_message_processing(
                    message_record_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    status=TriageRunItemStatus.CLASSIFYING,
                    failure_category=None,
                    successful_attempt_id=None,
                    seen_at=reserved_at,
                )
            self._connection.execute(
                "UPDATE email_triage_runs SET updated_at_utc = ? WHERE run_id = ?",
                (reserved_at.isoformat(), run_id),
            )
            self._connection.commit()
            return TriageReservation(
                TriageReservationStatus.NEW,
                evaluation_id=evaluation_id,
                attempt_id=attempt_id,
            )
        except BaseException:
            self._connection.rollback()
            raise

    def mark_attempt_running(
        self,
        *,
        attempt_id: int,
        run_id: str,
        ordinal: int,
        started_at: datetime,
    ) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE email_triage_attempts
                SET status = 'running', started_at_utc = ?
                WHERE id = ? AND run_id = ? AND item_ordinal = ? AND status = 'reserved'
                """,
                (started_at.isoformat(), attempt_id, run_id, ordinal),
            )
            _require_one(cursor, "triage attempt")
            self._connection.execute(
                "UPDATE email_triage_runs SET updated_at_utc = ? WHERE run_id = ?",
                (started_at.isoformat(), run_id),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def complete_attempt(
        self,
        *,
        attempt_id: int,
        run_id: str,
        ordinal: int,
        decision: TriageDecision,
        completion: CompletionResult,
        trace_id: str | None,
        trace_unavailable: bool,
        completed_at: datetime,
    ) -> None:
        usage = completion.usage
        if decision.source is not TriageDecisionSource.MODEL or decision.reason is None:
            raise ValueError("model completion requires a model triage decision")
        decision_sha256 = _decision_hash(decision)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE email_triage_attempts
                SET status = 'succeeded', completed_at_utc = ?, provider = ?,
                    model_alias = ?, queue_wait_seconds = ?, provider_seconds = ?,
                    total_seconds = ?, prompt_tokens = ?, completion_tokens = ?,
                    total_tokens = ?, label = ?, decision_sha256 = ?,
                    reason_chars = ?, reason_text = ?, trace_id = ?, trace_unavailable = ?
                WHERE id = ? AND run_id = ? AND item_ordinal = ?
                  AND status IN ('reserved', 'running')
                """,
                (
                    completed_at.isoformat(),
                    completion.provider,
                    completion.model_alias,
                    completion.timing.queue_wait_seconds,
                    completion.timing.provider_seconds,
                    completion.elapsed_seconds,
                    usage.prompt_tokens if usage else None,
                    usage.completion_tokens if usage else None,
                    usage.total_tokens if usage else None,
                    decision.label.value,
                    decision_sha256,
                    len(decision.reason),
                    decision.reason,
                    trace_id,
                    int(trace_unavailable),
                    attempt_id,
                    run_id,
                    ordinal,
                ),
            )
            _require_one(cursor, "triage attempt")
            self._set_item(
                run_id,
                ordinal,
                status=TriageRunItemStatus.SUCCEEDED,
                attempt_id=attempt_id,
                failure_category=None,
                completed_at=completed_at,
            )
            message_record_id = self._message_record_id(run_id, ordinal)
            if message_record_id is not None:
                self._set_message_processing(
                    message_record_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    status=TriageRunItemStatus.SUCCEEDED,
                    failure_category=None,
                    successful_attempt_id=attempt_id,
                    seen_at=completed_at,
                )
            self._connection.execute(
                "UPDATE email_triage_runs SET updated_at_utc = ? WHERE run_id = ?",
                (completed_at.isoformat(), run_id),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def complete_rule_attempt(
        self,
        *,
        attempt_id: int,
        run_id: str,
        ordinal: int,
        decision: TriageDecision,
        completed_at: datetime,
    ) -> None:
        if decision.source is not TriageDecisionSource.RULE or decision.reason is not None:
            raise ValueError("rule completion requires a deterministic triage decision")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE email_triage_attempts
                SET status = 'succeeded', completed_at_utc = ?,
                    provider_attempt_count = 0, label = ?, decision_sha256 = ?,
                    reason_chars = NULL, reason_text = NULL, trace_id = NULL,
                    trace_unavailable = 1, decision_source = 'rule',
                    rule_id = ?, rule_version = ?
                WHERE id = ? AND run_id = ? AND item_ordinal = ?
                  AND status IN ('reserved', 'running')
                """,
                (
                    completed_at.isoformat(),
                    decision.label.value,
                    _decision_hash(decision),
                    decision.rule_id,
                    decision.rule_version,
                    attempt_id,
                    run_id,
                    ordinal,
                ),
            )
            _require_one(cursor, "triage attempt")
            self._set_item(
                run_id,
                ordinal,
                status=TriageRunItemStatus.SUCCEEDED,
                attempt_id=attempt_id,
                failure_category=None,
                completed_at=completed_at,
            )
            message_record_id = self._message_record_id(run_id, ordinal)
            if message_record_id is not None:
                self._set_message_processing(
                    message_record_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    status=TriageRunItemStatus.SUCCEEDED,
                    failure_category=None,
                    successful_attempt_id=attempt_id,
                    seen_at=completed_at,
                )
            self._connection.execute(
                "UPDATE email_triage_runs SET updated_at_utc = ? WHERE run_id = ?",
                (completed_at.isoformat(), run_id),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def fail_attempt(
        self,
        *,
        attempt_id: int | None,
        run_id: str,
        ordinal: int,
        category: str,
        provider: str | None,
        model_alias: str | None,
        queue_wait_seconds: float,
        provider_seconds: float | None,
        attempt_count: int,
        retry_eligible: bool | None,
        retry_after_seconds: float | None,
        trace_id: str | None,
        trace_unavailable: bool,
        completed_at: datetime,
    ) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            if attempt_id is not None:
                cursor = self._connection.execute(
                    """
                    UPDATE email_triage_attempts
                    SET status = 'failed', completed_at_utc = ?, provider = ?,
                        model_alias = ?, queue_wait_seconds = ?, provider_seconds = ?,
                        total_seconds = ?, provider_attempt_count = ?,
                        retry_eligible = ?, retry_after_seconds = ?,
                        failure_category = ?, trace_id = ?, trace_unavailable = ?
                    WHERE id = ? AND run_id = ? AND item_ordinal = ?
                      AND status IN ('reserved', 'running')
                    """,
                    (
                        completed_at.isoformat(),
                        provider,
                        model_alias,
                        queue_wait_seconds,
                        provider_seconds,
                        (
                            queue_wait_seconds + provider_seconds
                            if provider_seconds is not None
                            else queue_wait_seconds
                        ),
                        attempt_count,
                        int(retry_eligible) if retry_eligible is not None else None,
                        retry_after_seconds,
                        category,
                        trace_id,
                        int(trace_unavailable),
                        attempt_id,
                        run_id,
                        ordinal,
                    ),
                )
                _require_one(cursor, "triage attempt")
            self._set_item(
                run_id,
                ordinal,
                status=TriageRunItemStatus.FAILED,
                attempt_id=attempt_id,
                failure_category=category,
                completed_at=completed_at,
            )
            message_record_id = self._message_record_id(run_id, ordinal)
            if message_record_id is not None:
                self._set_message_processing(
                    message_record_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    status=TriageRunItemStatus.FAILED,
                    failure_category=category,
                    successful_attempt_id=None,
                    seen_at=completed_at,
                )
            self._connection.execute(
                "UPDATE email_triage_runs SET updated_at_utc = ? WHERE run_id = ?",
                (completed_at.isoformat(), run_id),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def record_item_failure(
        self,
        run_id: str,
        *,
        ordinal: int,
        message_id: str | None,
        message_fingerprint: str,
        received_at: datetime | None,
        message_record_id: int | None,
        category: str,
        recorded_at: datetime,
        interrupted: bool = False,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO email_triage_run_items (
                run_id, ordinal, gmail_message_id, message_fingerprint,
                received_at_utc, message_record_id, status, failure_category,
                recorded_at_utc, completed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                ordinal,
                message_id,
                message_fingerprint,
                received_at.isoformat() if received_at else None,
                message_record_id,
                (
                    TriageRunItemStatus.INTERRUPTED.value
                    if interrupted
                    else TriageRunItemStatus.FAILED.value
                ),
                category,
                recorded_at.isoformat(),
                recorded_at.isoformat(),
            ),
        )
        if message_record_id is not None:
            self._set_message_processing(
                message_record_id,
                run_id=run_id,
                ordinal=ordinal,
                status=(
                    TriageRunItemStatus.INTERRUPTED if interrupted else TriageRunItemStatus.FAILED
                ),
                failure_category=category,
                successful_attempt_id=None,
                seen_at=recorded_at,
            )
        self._connection.execute(
            "UPDATE email_triage_runs SET updated_at_utc = ? WHERE run_id = ?",
            (recorded_at.isoformat(), run_id),
        )
        self._connection.commit()

    def interrupt_pending(
        self,
        run_id: str,
        *,
        starting_ordinal: int,
        completed_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            UPDATE email_triage_run_items
            SET status = 'interrupted', failure_category = 'interrupted',
                completed_at_utc = ?
            WHERE run_id = ? AND ordinal >= ?
              AND status IN ('pending', 'classifying')
            """,
            (completed_at.isoformat(), run_id, starting_ordinal),
        )
        self._connection.commit()

    def complete_run(
        self,
        run_id: str,
        *,
        status: TriageRunStatus,
        completed_at: datetime,
    ) -> None:
        if status not in {
            TriageRunStatus.COMPLETED_WITH_RESULTS,
            TriageRunStatus.COMPLETED_WITH_FAILURES,
            TriageRunStatus.INTERRUPTED,
        }:
            raise ValueError("triage run cannot be completed with this status")
        cursor = self._connection.execute(
            """
            UPDATE email_triage_runs
            SET status = ?, updated_at_utc = ?, completed_at_utc = ?,
                failure_category = CASE WHEN ? = 'interrupted' THEN 'interrupted' ELSE NULL END
            WHERE run_id = ?
            """,
            (
                status.value,
                completed_at.isoformat(),
                completed_at.isoformat(),
                status.value,
                run_id,
            ),
        )
        _require_one(cursor, "triage run")
        self._connection.commit()

    def recent(self, *, limit: int) -> list[TriageRunSummary]:
        validate_recent_run_limit(limit)
        rows = self._connection.execute(
            f"""
            SELECT r.*,
                {_count_sql("succeeded")} AS succeeded_count,
                {_count_sql("reused")} AS reused_count,
                {_count_sql("failed")} AS failed_count,
                {_count_sql("interrupted")} AS interrupted_count
            FROM email_triage_runs r
            ORDER BY r.requested_at_utc DESC, r.run_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_run_summary(row) for row in rows]

    def review_recent(
        self,
        *,
        limit: int,
        run_filter: TriageRunFilter,
    ) -> list[TriageRunSummary]:
        validate_recent_run_limit(limit)
        predicates = {
            TriageRunFilter.ALL: ("", ()),
            TriageRunFilter.COMPLETED: (
                "WHERE r.status = ?",
                (TriageRunStatus.COMPLETED_WITH_RESULTS.value,),
            ),
            TriageRunFilter.ISSUES: (
                "WHERE r.status IN (?, ?)",
                (
                    TriageRunStatus.COMPLETED_WITH_FAILURES.value,
                    TriageRunStatus.FAILED_BEFORE_ITEMS.value,
                ),
            ),
            TriageRunFilter.INTERRUPTED: (
                "WHERE r.status = ?",
                (TriageRunStatus.INTERRUPTED.value,),
            ),
        }
        where_sql, parameters = predicates[run_filter]
        rows = self._connection.execute(
            f"""
            SELECT r.*,
                {_count_sql("succeeded")} AS succeeded_count,
                {_count_sql("reused")} AS reused_count,
                {_count_sql("failed")} AS failed_count,
                {_count_sql("interrupted")} AS interrupted_count
            FROM email_triage_runs r
            {where_sql}
            ORDER BY r.requested_at_utc DESC, r.run_id DESC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()
        return [_run_summary(row) for row in rows]

    def get(self, run_id: str) -> TriageRunDetails | None:
        row = self._connection.execute(
            f"""
            SELECT r.*,
                {_count_sql("succeeded")} AS succeeded_count,
                {_count_sql("reused")} AS reused_count,
                {_count_sql("failed")} AS failed_count,
                {_count_sql("interrupted")} AS interrupted_count
            FROM email_triage_runs r WHERE r.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        items = self._connection.execute(
            """
            SELECT i.ordinal, i.message_fingerprint, i.received_at_utc,
                i.status, i.failure_category, i.selected_attempt_id,
                a.label, a.decision_sha256, a.reason_chars, a.trace_id,
                a.decision_source, a.rule_id, a.rule_version,
                a.queue_wait_seconds, a.provider_seconds,
                a.total_seconds, a.prompt_tokens, a.completion_tokens, a.total_tokens,
                e.prompt_source, e.prompt_version, e.profile_version, e.model_alias,
                CASE WHEN i.gmail_message_id IS NOT NULL
                    AND a.label IS NOT NULL
                    AND e.normalized_sha256 IS NOT NULL
                    AND e.model_input_sha256 IS NOT NULL
                    AND e.model_message_chars IS NOT NULL
                    THEN 1 ELSE 0 END AS review_available
            FROM email_triage_run_items i
            LEFT JOIN email_triage_attempts a ON a.id = i.selected_attempt_id
            LEFT JOIN email_triage_evaluations e ON e.id = i.evaluation_id
            WHERE i.run_id = ?
            ORDER BY i.ordinal
            """,
            (run_id,),
        ).fetchall()
        return TriageRunDetails(
            run=_run_summary(row),
            items=tuple(_item_summary(item) for item in items),
        )

    def review_reference(
        self,
        run_id: str,
        ordinal: int,
    ) -> TriageReviewReference | None:
        row = self._connection.execute(
            """
            SELECT i.run_id, i.ordinal, i.gmail_message_id, i.message_fingerprint,
                i.status, a.label, e.normalized_sha256, e.model_input_sha256,
                e.model_message_chars
            FROM email_triage_run_items i
            LEFT JOIN email_triage_attempts a ON a.id = i.selected_attempt_id
            LEFT JOIN email_triage_evaluations e ON e.id = i.evaluation_id
            WHERE i.run_id = ? AND i.ordinal = ?
            """,
            (run_id, ordinal),
        ).fetchone()
        if row is None:
            return None
        return TriageReviewReference(
            run_id=str(row["run_id"]),
            ordinal=int(row["ordinal"]),
            message_id=(
                EmailMessageId(str(row["gmail_message_id"]))
                if row["gmail_message_id"] is not None
                else None
            ),
            message_fingerprint=str(row["message_fingerprint"]),
            item_status=TriageRunItemStatus(str(row["status"])),
            label=TriageLabel(str(row["label"])) if row["label"] is not None else None,
            normalized_sha256=(
                str(row["normalized_sha256"]) if row["normalized_sha256"] is not None else None
            ),
            model_input_sha256=(
                str(row["model_input_sha256"]) if row["model_input_sha256"] is not None else None
            ),
            model_message_chars=(
                int(row["model_message_chars"]) if row["model_message_chars"] is not None else None
            ),
        )

    def message_page(
        self,
        *,
        limit: int,
        message_filter: TriageMessageFilter,
        label: TriageLabel | None,
        cursor: TriageMessageCursor | None,
    ) -> TriageMessagePage:
        validate_message_limit(limit)
        predicates: list[str] = []
        parameters: list[object] = []
        if message_filter is TriageMessageFilter.RECOMMENDATIONS:
            predicates.append("m.latest_successful_attempt_id IS NOT NULL")
        elif message_filter is TriageMessageFilter.ISSUES:
            predicates.append(
                "m.latest_status IN ('pending', 'classifying', 'failed', 'interrupted')"
            )
        if label is not None:
            predicates.append("a.label = ?")
            parameters.append(label.value)
        if cursor is not None:
            predicates.append(
                "(m.received_at_utc < ? OR (m.received_at_utc = ? AND m.record_id < ?))"
            )
            cursor_value = cursor.received_at.isoformat()
            parameters.extend((cursor_value, cursor_value, cursor.record_id))
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        rows = self._connection.execute(
            f"""
            SELECT m.record_id, m.received_at_utc, m.latest_status,
                m.latest_failure_category, m.last_seen_at_utc,
                s.sender, s.subject, s.model_input_truncated, s.source_truncated,
                a.label, a.reason_text, a.decision_source, a.rule_id, a.rule_version
            FROM email_triage_messages m
            JOIN email_triage_content_snapshots s
              ON s.id = m.current_content_snapshot_id
            LEFT JOIN email_triage_attempts a
              ON a.id = m.latest_successful_attempt_id
            {where_sql}
            ORDER BY m.received_at_utc DESC, m.record_id DESC
            LIMIT ?
            """,
            (*parameters, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(_message_summary(row) for row in visible)
        next_cursor = None
        if has_more and visible:
            last = visible[-1]
            next_cursor = TriageMessageCursor(
                received_at=datetime.fromisoformat(str(last["received_at_utc"])),
                record_id=str(last["record_id"]),
            )
        return TriageMessagePage(items=items, next_cursor=next_cursor)

    def message_detail(self, record_id: str) -> TriageMessageDetail | None:
        row = self._connection.execute(
            """
            SELECT m.record_id, m.received_at_utc, m.latest_run_id,
                m.latest_item_ordinal, m.latest_status, m.latest_failure_category,
                m.last_seen_at_utc, m.latest_successful_attempt_id,
                s.sender, s.subject, s.normalized_text, s.model_input,
                s.normalized_sha256, s.model_input_sha256, s.original_size_bytes,
                s.content_source, s.cleanup_flags_json, s.source_truncated,
                s.model_input_truncated, s.metadata_truncated,
                a.decision_sha256, a.provider, a.model_alias, a.trace_id,
                a.prompt_tokens, a.completion_tokens, a.total_tokens,
                a.queue_wait_seconds, a.provider_seconds, a.total_seconds,
                a.label, a.reason_text, a.run_id AS successful_run_id,
                a.decision_source, a.rule_id, a.rule_version,
                a.item_ordinal AS successful_item_ordinal,
                e.prompt_source, e.prompt_version, e.profile_version,
                e.taxonomy_version, e.schema_version, e.generation_parameters_version
            FROM email_triage_messages m
            JOIN email_triage_content_snapshots s
              ON s.id = m.current_content_snapshot_id
            LEFT JOIN email_triage_attempts a
              ON a.id = m.latest_successful_attempt_id
            LEFT JOIN email_triage_evaluations e
              ON e.id = a.evaluation_id
            WHERE m.record_id = ?
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        summary = _message_summary(row)
        evidence_run_id = (
            str(row["successful_run_id"])
            if row["successful_run_id"] is not None
            else str(row["latest_run_id"])
        )
        evidence_item_ordinal = (
            int(row["successful_item_ordinal"])
            if row["successful_item_ordinal"] is not None
            else int(row["latest_item_ordinal"])
        )
        technical = TriageMessageTechnicalEvidence(
            run_id=evidence_run_id,
            item_ordinal=evidence_item_ordinal,
            attempt_id=(
                int(row["latest_successful_attempt_id"])
                if row["latest_successful_attempt_id"] is not None
                else None
            ),
            decision_sha256=(
                str(row["decision_sha256"]) if row["decision_sha256"] is not None else None
            ),
            prompt_source=(
                PromptSourceKind(str(row["prompt_source"]))
                if row["prompt_source"] is not None
                else None
            ),
            prompt_version=(
                str(row["prompt_version"]) if row["prompt_version"] is not None else None
            ),
            profile_version=(
                str(row["profile_version"]) if row["profile_version"] is not None else None
            ),
            taxonomy_version=(
                str(row["taxonomy_version"]) if row["taxonomy_version"] is not None else None
            ),
            schema_version=(
                str(row["schema_version"]) if row["schema_version"] is not None else None
            ),
            generation_parameters_version=(
                str(row["generation_parameters_version"])
                if row["generation_parameters_version"] is not None
                else None
            ),
            provider=str(row["provider"]) if row["provider"] is not None else None,
            model_alias=str(row["model_alias"]) if row["model_alias"] is not None else None,
            trace_id=str(row["trace_id"]) if row["trace_id"] is not None else None,
            prompt_tokens=(int(row["prompt_tokens"]) if row["prompt_tokens"] is not None else None),
            completion_tokens=(
                int(row["completion_tokens"]) if row["completion_tokens"] is not None else None
            ),
            total_tokens=(int(row["total_tokens"]) if row["total_tokens"] is not None else None),
            queue_wait_seconds=(
                float(row["queue_wait_seconds"]) if row["queue_wait_seconds"] is not None else None
            ),
            provider_seconds=(
                float(row["provider_seconds"]) if row["provider_seconds"] is not None else None
            ),
            total_seconds=(
                float(row["total_seconds"]) if row["total_seconds"] is not None else None
            ),
            decision_source=(
                TriageDecisionSource(str(row["decision_source"]))
                if row["decision_source"] is not None
                else None
            ),
            rule_id=str(row["rule_id"]) if row["rule_id"] is not None else None,
            rule_version=(str(row["rule_version"]) if row["rule_version"] is not None else None),
        )
        return TriageMessageDetail(
            summary=summary,
            normalized_text=str(row["normalized_text"]),
            model_input=str(row["model_input"]),
            normalized_sha256=str(row["normalized_sha256"]),
            model_input_sha256=str(row["model_input_sha256"]),
            original_size_bytes=int(row["original_size_bytes"]),
            content_source=EmailContentSource(str(row["content_source"])),
            cleanup_flags=tuple(json.loads(str(row["cleanup_flags_json"]))),
            metadata_truncated=bool(row["metadata_truncated"]),
            technical=technical,
        )

    def _insert_evaluation(
        self,
        identity: TriageEvaluationIdentity,
        created_at: datetime,
    ) -> None:
        evidence = identity.input
        self._connection.execute(
            """
            INSERT INTO email_triage_evaluations (
                identity_sha256, gmail_message_id, gmail_thread_id,
                received_at_utc, message_fingerprint, normalized_sha256,
                model_input_sha256, sender_chars, subject_chars,
                normalized_chars, model_message_chars, original_size_bytes,
                content_source, source_truncated, model_input_truncated,
                metadata_truncated, cleanup_flags_json, profile_name,
                profile_version, taxonomy_version, schema_version,
                generation_parameters_version, prompt_name, prompt_source,
                prompt_version, model_alias, created_at_utc,
                decision_source, rule_id, rule_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(identity_sha256) DO NOTHING
            """,
            (
                identity.identity_sha256,
                evidence.message_id.value,
                evidence.thread_id.value,
                evidence.received_at.isoformat(),
                evidence.message_fingerprint,
                evidence.normalized_sha256,
                evidence.model_input_sha256,
                evidence.sender_chars,
                evidence.subject_chars,
                evidence.normalized_chars,
                evidence.model_message_chars,
                evidence.original_size_bytes,
                evidence.content_source.value,
                int(evidence.source_truncated),
                int(evidence.model_input_truncated),
                int(evidence.metadata_truncated),
                json.dumps(evidence.cleanup_flags, separators=(",", ":")),
                identity.profile_name,
                identity.profile_version,
                identity.taxonomy_version,
                identity.schema_version,
                identity.generation_parameters_version,
                identity.prompt.name,
                identity.prompt.source.value,
                identity.prompt.version,
                identity.model_alias,
                created_at.isoformat(),
                identity.decision_source.value,
                identity.rule_id,
                identity.rule_version,
            ),
        )

    def _set_item(
        self,
        run_id: str,
        ordinal: int,
        *,
        status: TriageRunItemStatus,
        attempt_id: int | None,
        failure_category: str | None,
        completed_at: datetime | None,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_run_items
            SET status = ?, selected_attempt_id = ?, failure_category = ?,
                completed_at_utc = ?
            WHERE run_id = ? AND ordinal = ?
            """,
            (
                status.value,
                attempt_id,
                failure_category,
                completed_at.isoformat() if completed_at else None,
                run_id,
                ordinal,
            ),
        )
        _require_one(cursor, "triage run item")

    def _message_record_id(self, run_id: str, ordinal: int) -> int | None:
        row = self._connection.execute(
            """
            SELECT message_record_id FROM email_triage_run_items
            WHERE run_id = ? AND ordinal = ?
            """,
            (run_id, ordinal),
        ).fetchone()
        if row is None or row["message_record_id"] is None:
            return None
        return int(row["message_record_id"])

    def _set_message_processing(
        self,
        message_record_id: int,
        *,
        run_id: str,
        ordinal: int,
        status: TriageRunItemStatus,
        failure_category: str | None,
        successful_attempt_id: int | None,
        seen_at: datetime,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_messages
            SET latest_run_id = ?, latest_item_ordinal = ?, latest_status = ?,
                latest_failure_category = ?,
                latest_successful_attempt_id = COALESCE(?, latest_successful_attempt_id),
                last_seen_at_utc = ?
            WHERE id = ?
            """,
            (
                run_id,
                ordinal,
                status.value,
                failure_category,
                successful_attempt_id,
                seen_at.isoformat(),
                message_record_id,
            ),
        )
        _require_one(cursor, "triage message")

    def _update_run_state(
        self,
        run_id: str,
        status: TriageRunStatus,
        updated_at: datetime,
    ) -> None:
        cursor = self._connection.execute(
            "UPDATE email_triage_runs SET status = ?, updated_at_utc = ? WHERE run_id = ?",
            (status.value, updated_at.isoformat(), run_id),
        )
        _require_one(cursor, "triage run")
        self._connection.commit()


def _run_summary(row: sqlite3.Row) -> TriageRunSummary:
    return TriageRunSummary(
        run_id=str(row["run_id"]),
        status=TriageRunStatus(str(row["status"])),
        query_sha256=str(row["query_sha256"]),
        requested_limit=int(row["requested_limit"]),
        force_new_attempt=bool(row["force_new_attempt"]),
        requested_at=datetime.fromisoformat(str(row["requested_at_utc"])),
        completed_at=(
            datetime.fromisoformat(str(row["completed_at_utc"]))
            if row["completed_at_utc"] is not None
            else None
        ),
        document_count=int(row["document_count"]),
        retrieval_failure_count=int(row["retrieval_failure_count"]),
        succeeded_count=int(row["succeeded_count"]),
        reused_count=int(row["reused_count"]),
        failed_count=int(row["failed_count"]),
        interrupted_count=int(row["interrupted_count"]),
        query_text=(str(row["query_text"]) if row["query_text"] is not None else None),
    )


def _item_summary(row: sqlite3.Row) -> TriageRunItemSummary:
    return TriageRunItemSummary(
        ordinal=int(row["ordinal"]),
        message_fingerprint=str(row["message_fingerprint"]),
        received_at=(
            datetime.fromisoformat(str(row["received_at_utc"]))
            if row["received_at_utc"] is not None
            else None
        ),
        status=TriageRunItemStatus(str(row["status"])),
        label=TriageLabel(str(row["label"])) if row["label"] is not None else None,
        decision_sha256=(
            str(row["decision_sha256"]) if row["decision_sha256"] is not None else None
        ),
        reason_chars=(int(row["reason_chars"]) if row["reason_chars"] is not None else None),
        failure_category=(
            str(row["failure_category"]) if row["failure_category"] is not None else None
        ),
        prompt_source=(
            PromptSourceKind(str(row["prompt_source"]))
            if row["prompt_source"] is not None
            else None
        ),
        prompt_version=(str(row["prompt_version"]) if row["prompt_version"] is not None else None),
        profile_version=(
            str(row["profile_version"]) if row["profile_version"] is not None else None
        ),
        model_alias=str(row["model_alias"]) if row["model_alias"] is not None else None,
        trace_id=str(row["trace_id"]) if row["trace_id"] is not None else None,
        queue_wait_seconds=(
            float(row["queue_wait_seconds"]) if row["queue_wait_seconds"] is not None else None
        ),
        provider_seconds=(
            float(row["provider_seconds"]) if row["provider_seconds"] is not None else None
        ),
        total_seconds=(float(row["total_seconds"]) if row["total_seconds"] is not None else None),
        prompt_tokens=(int(row["prompt_tokens"]) if row["prompt_tokens"] is not None else None),
        completion_tokens=(
            int(row["completion_tokens"]) if row["completion_tokens"] is not None else None
        ),
        total_tokens=int(row["total_tokens"]) if row["total_tokens"] is not None else None,
        attempt_id=(
            int(row["selected_attempt_id"]) if row["selected_attempt_id"] is not None else None
        ),
        review_available=bool(row["review_available"]),
        decision_source=(
            TriageDecisionSource(str(row["decision_source"]))
            if row["decision_source"] is not None
            else None
        ),
        rule_id=str(row["rule_id"]) if row["rule_id"] is not None else None,
        rule_version=(str(row["rule_version"]) if row["rule_version"] is not None else None),
    )


def _message_summary(row: sqlite3.Row) -> TriageMessageSummary:
    label = TriageLabel(str(row["label"])) if row["label"] is not None else None
    reason = str(row["reason_text"]) if row["reason_text"] is not None else None
    return TriageMessageSummary(
        record_id=str(row["record_id"]),
        received_at=datetime.fromisoformat(str(row["received_at_utc"])),
        sender=str(row["sender"]),
        subject=str(row["subject"]),
        label=label,
        reason=reason,
        latest_status=TriageRunItemStatus(str(row["latest_status"])),
        latest_failure_category=(
            str(row["latest_failure_category"])
            if row["latest_failure_category"] is not None
            else None
        ),
        last_triaged_at=datetime.fromisoformat(str(row["last_seen_at_utc"])),
        model_input_truncated=bool(row["model_input_truncated"]),
        source_truncated=bool(row["source_truncated"]),
        has_recommendation=label is not None,
        decision_source=(
            TriageDecisionSource(str(row["decision_source"]))
            if row["decision_source"] is not None
            else None
        ),
        rule_id=str(row["rule_id"]) if row["rule_id"] is not None else None,
        rule_version=(str(row["rule_version"]) if row["rule_version"] is not None else None),
    )


def _count_sql(status: str) -> str:
    return (
        "(SELECT COUNT(*) FROM email_triage_run_items i "
        f"WHERE i.run_id = r.run_id AND i.status = '{status}')"
    )


def _decision_hash(decision: TriageDecision) -> str:
    value = json.dumps(
        {
            "label": decision.label.value,
            "reason": decision.reason,
            "source": decision.source.value,
            "rule_id": decision.rule_id,
            "rule_version": decision.rule_version,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _sha256(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("SQLite did not return a row ID")
    return int(cursor.lastrowid)


def _require_one(cursor: sqlite3.Cursor, label: str) -> None:
    if cursor.rowcount != 1:
        raise sqlite3.DatabaseError(f"{label} was not found")
