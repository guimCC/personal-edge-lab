"""SQLite evidence repository for durable read-only mailbox triage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from personal_edge_lab.domain.ai import CompletionResult
from personal_edge_lab.domain.email import EmailItemFailure
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriageDecision,
    TriageLabel,
)
from personal_edge_lab.domain.email_triage_runs import (
    StoredTriageDecision,
    TriageEvaluationIdentity,
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
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO email_triage_runs (
                run_id, operation_id, query_sha256, requested_limit,
                force_new_attempt, status, requested_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, 'requested', ?, ?)
            """,
            (
                run_id,
                operation_id,
                query_sha256,
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
            category=failure.category.value,
            recorded_at=recorded_at,
        )

    def reserve(
        self,
        run_id: str,
        *,
        ordinal: int,
        identity: TriageEvaluationIdentity,
        operation_id: str,
        force_new_attempt: bool,
        reserved_at: datetime,
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
            self._connection.execute(
                """
                INSERT INTO email_triage_run_items (
                    run_id, ordinal, gmail_message_id, message_fingerprint,
                    received_at_utc, evaluation_id, status, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    run_id,
                    ordinal,
                    identity.input.message_id.value,
                    identity.input.message_fingerprint,
                    identity.input.received_at.isoformat(),
                    evaluation_id,
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
                self._connection.commit()
                return TriageReservation(
                    TriageReservationStatus.CONCURRENT,
                    evaluation_id=evaluation_id,
                    attempt_id=attempt_id,
                )

            succeeded = self._connection.execute(
                """
                SELECT id, label, decision_sha256, reason_chars, trace_id
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
                    reason_chars=int(succeeded["reason_chars"]),
                )
                self._set_item(
                    run_id,
                    ordinal,
                    status=TriageRunItemStatus.REUSED,
                    attempt_id=attempt_id,
                    failure_category=None,
                    completed_at=reserved_at,
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
                    attempt_number, status, reserved_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'reserved', ?)
                """,
                (
                    evaluation_id,
                    run_id,
                    ordinal,
                    operation_id,
                    next_number,
                    reserved_at.isoformat(),
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
                    reason_chars = ?, trace_id = ?, trace_unavailable = ?
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
        category: str,
        recorded_at: datetime,
        interrupted: bool = False,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO email_triage_run_items (
                run_id, ordinal, gmail_message_id, message_fingerprint,
                received_at_utc, status, failure_category,
                recorded_at_utc, completed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                ordinal,
                message_id,
                message_fingerprint,
                received_at.isoformat() if received_at else None,
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
                a.label, a.trace_id, a.queue_wait_seconds, a.provider_seconds,
                a.total_seconds, a.prompt_tokens, a.completion_tokens, a.total_tokens,
                e.prompt_source, e.prompt_version, e.profile_version, e.model_alias
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
                prompt_version, model_alias, created_at_utc
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
    )


def _count_sql(status: str) -> str:
    return (
        "(SELECT COUNT(*) FROM email_triage_run_items i "
        f"WHERE i.run_id = r.run_id AND i.status = '{status}')"
    )


def _decision_hash(decision: TriageDecision) -> str:
    value = json.dumps(
        {"label": decision.label.value, "reason": decision.reason},
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
