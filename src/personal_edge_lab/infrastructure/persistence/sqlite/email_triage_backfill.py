"""SQLite repository for bounded, resumable historical triage backfills."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from personal_edge_lab.domain.email import (
    EmailMessageId,
    EmailRetrievalCursor,
)
from personal_edge_lab.domain.email_triage_backfill import (
    BACKFILL_MONTHS,
    TriageBackfillJob,
    TriageBackfillSegment,
    TriageBackfillSegmentStatus,
    TriageBackfillStatus,
)
from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection


class SqliteTriageBackfillRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = open_connection(database_path, timeout_seconds=timeout_seconds)

    def __enter__(self) -> SqliteTriageBackfillRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def create_job(
        self,
        *,
        job_id: str,
        starts_at: datetime,
        ends_at: datetime,
        max_messages: int,
        segments: tuple[tuple[datetime, datetime], ...],
        created_at: datetime,
    ) -> None:
        if len(segments) != BACKFILL_MONTHS:
            raise ValueError("historical backfill requires exactly 12 segments")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                INSERT INTO email_triage_backfill_jobs (
                    job_id, status, scope_version, starts_at_utc, ends_at_utc,
                    months, max_messages, created_at_utc, updated_at_utc
                ) VALUES (?, 'ready', 'received-mail-v1', ?, ?, 12, ?, ?, ?)
                """,
                (
                    job_id,
                    starts_at.isoformat(),
                    ends_at.isoformat(),
                    max_messages,
                    created_at.isoformat(),
                    created_at.isoformat(),
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO email_triage_backfill_segments (
                    job_id, ordinal, starts_at_utc, ends_at_utc,
                    status, updated_at_utc
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                [
                    (
                        job_id,
                        ordinal,
                        segment_start.isoformat(),
                        segment_end.isoformat(),
                        created_at.isoformat(),
                    )
                    for ordinal, (segment_start, segment_end) in enumerate(segments, start=1)
                ],
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def get_job(self, job_id: str) -> TriageBackfillJob | None:
        row = self._connection.execute(
            _JOB_SELECT + " WHERE jobs.job_id = ?",
            (job_id,),
        ).fetchone()
        return _job(row) if row is not None else None

    def recent_jobs(self, *, limit: int) -> list[TriageBackfillJob]:
        if not 1 <= limit <= 100:
            raise ValueError("backfill history limit must be from 1 through 100")
        rows = self._connection.execute(
            _JOB_SELECT + " ORDER BY jobs.created_at_utc DESC, jobs.job_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_job(row) for row in rows]

    def active_segment(self, job_id: str) -> TriageBackfillSegment | None:
        row = self._connection.execute(
            """
            SELECT ordinal, starts_at_utc, ends_at_utc, status,
                   page_cursor, discovered_count
            FROM email_triage_backfill_segments
            WHERE job_id = ? AND status != 'exhausted'
            ORDER BY ordinal
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        cursor = (
            EmailRetrievalCursor(str(row["page_cursor"]))
            if row["page_cursor"] is not None
            else None
        )
        return TriageBackfillSegment(
            ordinal=int(row["ordinal"]),
            starts_at=datetime.fromisoformat(str(row["starts_at_utc"])),
            ends_at=datetime.fromisoformat(str(row["ends_at_utc"])),
            status=TriageBackfillSegmentStatus(str(row["status"])),
            cursor=cursor,
            discovered_count=int(row["discovered_count"]),
        )

    def record_discovery(
        self,
        *,
        job_id: str,
        segment_ordinal: int,
        message_ids: tuple[EmailMessageId, ...],
        next_cursor: str | None,
        updated_at: datetime,
    ) -> int:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            job_row = self._connection.execute(
                """
                SELECT max_messages,
                       (SELECT COUNT(*) FROM email_triage_backfill_items
                        WHERE job_id = ?) AS discovered_count
                FROM email_triage_backfill_jobs WHERE job_id = ?
                """,
                (job_id, job_id),
            ).fetchone()
            if job_row is None:
                raise LookupError("backfill job not found")
            remaining = max(0, int(job_row["max_messages"]) - int(job_row["discovered_count"]))
            inserted = 0
            for message_id in message_ids[:remaining]:
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO email_triage_backfill_items (
                        job_id, segment_ordinal, gmail_message_id, status,
                        discovered_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        job_id,
                        segment_ordinal,
                        message_id.value,
                        updated_at.isoformat(),
                        updated_at.isoformat(),
                    ),
                )
                inserted += cursor.rowcount
            total = int(job_row["discovered_count"]) + inserted
            limit_reached = total >= int(job_row["max_messages"])
            segment_status = "exhausted" if next_cursor is None else "discovering"
            self._connection.execute(
                """
                UPDATE email_triage_backfill_segments
                SET status = ?, page_cursor = ?, discovered_count = discovered_count + ?,
                    updated_at_utc = ?
                WHERE job_id = ? AND ordinal = ?
                """,
                (
                    segment_status,
                    next_cursor,
                    inserted,
                    updated_at.isoformat(),
                    job_id,
                    segment_ordinal,
                ),
            )
            self._connection.execute(
                """
                UPDATE email_triage_backfill_jobs
                SET status = ?, updated_at_utc = ?
                WHERE job_id = ?
                """,
                (
                    "limit_reached" if limit_reached else "running",
                    updated_at.isoformat(),
                    job_id,
                ),
            )
            self._connection.commit()
            return inserted
        except BaseException:
            self._connection.rollback()
            raise

    def claim_pending(
        self,
        *,
        job_id: str,
        limit: int,
        claimed_at: datetime,
    ) -> list[tuple[int, EmailMessageId, str]]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self._connection.execute(
                """
                SELECT id, gmail_message_id, process_attempts
                FROM email_triage_backfill_items
                WHERE job_id = ? AND status = 'pending'
                ORDER BY segment_ordinal, id
                LIMIT ?
                """,
                (job_id, limit),
            ).fetchall()
            claimed: list[tuple[int, EmailMessageId, str]] = []
            for row in rows:
                item_id = int(row["id"])
                attempt = int(row["process_attempts"]) + 1
                child_run_id = uuid5(
                    NAMESPACE_URL,
                    f"personal-edge-lab:backfill:{job_id}:{item_id}:{attempt}",
                ).hex
                self._connection.execute(
                    """
                    UPDATE email_triage_backfill_items
                    SET status = 'processing', process_attempts = ?,
                        child_run_id = NULL, failure_category = NULL,
                        updated_at_utc = ?, completed_at_utc = NULL
                    WHERE id = ? AND status = 'pending'
                    """,
                    (attempt, claimed_at.isoformat(), item_id),
                )
                claimed.append(
                    (item_id, EmailMessageId(str(row["gmail_message_id"])), child_run_id)
                )
            if claimed:
                self._connection.execute(
                    """
                    UPDATE email_triage_backfill_jobs
                    SET status = 'running', updated_at_utc = ?
                    WHERE job_id = ?
                    """,
                    (claimed_at.isoformat(), job_id),
                )
            self._connection.commit()
            return claimed
        except BaseException:
            self._connection.rollback()
            raise

    def complete_item(
        self,
        *,
        item_id: int,
        status: str,
        child_run_id: str,
        completed_at: datetime,
    ) -> None:
        if status not in {"succeeded", "reused"}:
            raise ValueError("backfill completion status is invalid")
        cursor = self._connection.execute(
            """
            UPDATE email_triage_backfill_items
            SET status = ?, child_run_id = ?, failure_category = NULL,
                updated_at_utc = ?, completed_at_utc = ?
            WHERE id = ? AND status = 'processing'
            """,
            (
                status,
                child_run_id,
                completed_at.isoformat(),
                completed_at.isoformat(),
                item_id,
            ),
        )
        _require_one(cursor, "backfill item")
        self._connection.commit()

    def fail_item(
        self,
        *,
        item_id: int,
        category: str,
        completed_at: datetime,
        interrupted: bool = False,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_backfill_items
            SET status = ?, failure_category = ?, updated_at_utc = ?,
                completed_at_utc = ?
            WHERE id = ? AND status = 'processing'
            """,
            (
                "interrupted" if interrupted else "failed",
                category,
                completed_at.isoformat(),
                completed_at.isoformat(),
                item_id,
            ),
        )
        _require_one(cursor, "backfill item")
        self._connection.commit()

    def pause_job(self, job_id: str, *, updated_at: datetime) -> None:
        self._connection.execute(
            """
            UPDATE email_triage_backfill_jobs SET status = 'paused', updated_at_utc = ?
            WHERE job_id = ? AND status IN ('ready', 'running')
            """,
            (updated_at.isoformat(), job_id),
        )
        self._connection.commit()

    def cancel_job(self, job_id: str, *, updated_at: datetime) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE email_triage_backfill_jobs
                SET status = 'cancelled', updated_at_utc = ?, completed_at_utc = ?
                WHERE job_id = ?
                  AND status IN ('ready', 'running', 'paused', 'limit_reached')
                """,
                (updated_at.isoformat(), updated_at.isoformat(), job_id),
            )
            _require_one(cursor, "backfill job")
            self._connection.execute(
                """
                UPDATE email_triage_backfill_items
                SET status = 'interrupted', failure_category = 'cancelled',
                    updated_at_utc = ?, completed_at_utc = ?
                WHERE job_id = ? AND status IN ('pending', 'processing')
                """,
                (updated_at.isoformat(), updated_at.isoformat(), job_id),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def finalize_job(self, job_id: str, *, updated_at: datetime) -> TriageBackfillJob:
        job = self.get_job(job_id)
        if job is None:
            raise LookupError("backfill job not found")
        if job.status is TriageBackfillStatus.CANCELLED:
            return job
        pending = job.pending_count
        if job.segments_exhausted == BACKFILL_MONTHS and pending == 0:
            status = (
                TriageBackfillStatus.COMPLETED_WITH_FAILURES
                if job.failed_count or job.interrupted_count
                else TriageBackfillStatus.COMPLETED
            )
        elif job.discovered_count >= job.max_messages:
            status = TriageBackfillStatus.LIMIT_REACHED
        else:
            status = TriageBackfillStatus.PAUSED
        self._connection.execute(
            """
            UPDATE email_triage_backfill_jobs
            SET status = ?, updated_at_utc = ?, completed_at_utc = ?
            WHERE job_id = ?
            """,
            (
                status.value,
                updated_at.isoformat(),
                (
                    updated_at.isoformat()
                    if status
                    in {
                        TriageBackfillStatus.COMPLETED,
                        TriageBackfillStatus.COMPLETED_WITH_FAILURES,
                    }
                    else None
                ),
                job_id,
            ),
        )
        self._connection.commit()
        result = self.get_job(job_id)
        assert result is not None
        return result

    def recover_interrupted(self, job_id: str, *, recovered_at: datetime) -> int:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_backfill_items
            SET status = 'interrupted', failure_category = 'interrupted',
                updated_at_utc = ?, completed_at_utc = ?
            WHERE job_id = ? AND status = 'processing'
            """,
            (recovered_at.isoformat(), recovered_at.isoformat(), job_id),
        )
        self._connection.commit()
        return cursor.rowcount

    def retry_failures(self, job_id: str, *, updated_at: datetime) -> int:
        cursor = self._connection.execute(
            """
            UPDATE email_triage_backfill_items
            SET status = 'pending', failure_category = NULL,
                updated_at_utc = ?, completed_at_utc = NULL
            WHERE job_id = ? AND status IN ('failed', 'interrupted')
            """,
            (updated_at.isoformat(), job_id),
        )
        self._connection.commit()
        return cursor.rowcount


_JOB_SELECT = """
SELECT jobs.*,
       (SELECT COUNT(*) FROM email_triage_backfill_items items
        WHERE items.job_id = jobs.job_id) AS discovered_count,
       (SELECT COUNT(*) FROM email_triage_backfill_items items
        WHERE items.job_id = jobs.job_id
          AND items.status IN ('pending', 'processing')) AS pending_count,
       (SELECT COUNT(*) FROM email_triage_backfill_items items
        WHERE items.job_id = jobs.job_id AND items.status = 'succeeded') AS succeeded_count,
       (SELECT COUNT(*) FROM email_triage_backfill_items items
        WHERE items.job_id = jobs.job_id AND items.status = 'reused') AS reused_count,
       (SELECT COUNT(*) FROM email_triage_backfill_items items
        WHERE items.job_id = jobs.job_id AND items.status = 'failed') AS failed_count,
       (SELECT COUNT(*) FROM email_triage_backfill_items items
        WHERE items.job_id = jobs.job_id AND items.status = 'interrupted') AS interrupted_count,
       (SELECT COUNT(*) FROM email_triage_backfill_segments segments
        WHERE segments.job_id = jobs.job_id
          AND segments.status = 'exhausted') AS segments_exhausted,
       (SELECT MIN(ordinal) FROM email_triage_backfill_segments segments
        WHERE segments.job_id = jobs.job_id
          AND segments.status != 'exhausted') AS active_segment
FROM email_triage_backfill_jobs jobs
"""


def _job(row: sqlite3.Row) -> TriageBackfillJob:
    return TriageBackfillJob(
        job_id=str(row["job_id"]),
        status=TriageBackfillStatus(str(row["status"])),
        starts_at=datetime.fromisoformat(str(row["starts_at_utc"])),
        ends_at=datetime.fromisoformat(str(row["ends_at_utc"])),
        max_messages=int(row["max_messages"]),
        created_at=datetime.fromisoformat(str(row["created_at_utc"])),
        updated_at=datetime.fromisoformat(str(row["updated_at_utc"])),
        discovered_count=int(row["discovered_count"]),
        pending_count=int(row["pending_count"]),
        succeeded_count=int(row["succeeded_count"]),
        reused_count=int(row["reused_count"]),
        failed_count=int(row["failed_count"]),
        interrupted_count=int(row["interrupted_count"]),
        segments_exhausted=int(row["segments_exhausted"]),
        active_segment=(int(row["active_segment"]) if row["active_segment"] is not None else None),
    )


def _require_one(cursor: sqlite3.Cursor, label: str) -> None:
    if cursor.rowcount != 1:
        raise LookupError(f"{label} was not in the expected state")
