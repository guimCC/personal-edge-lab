"""SQLite persistence for collector runtime status."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from personal_edge_lab.application.ports.telemetry import SourceFailureCategory
from personal_edge_lab.domain.telemetry import (
    CollectionAttemptOutcome,
    CollectorRuntimeStatus,
)


class SqliteCollectorStatusRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = sqlite3.connect(database_path, timeout=timeout_seconds)
        self._connection.row_factory = sqlite3.Row

    def __enter__(self) -> SqliteCollectorStatusRepository:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def start(self, device_id: str, *, started_at: datetime) -> None:
        timestamp = started_at.isoformat()
        self._connection.execute(
            """
            INSERT INTO collector_runtime_status (
                device_id, process_started_at_utc, heartbeat_at_utc,
                stopped_at_utc, consecutive_failures
            ) VALUES (?, ?, ?, NULL, 0)
            ON CONFLICT(device_id) DO UPDATE SET
                process_started_at_utc = excluded.process_started_at_utc,
                heartbeat_at_utc = excluded.heartbeat_at_utc,
                stopped_at_utc = NULL,
                last_attempt_at_utc = NULL,
                last_attempt_outcome = NULL,
                consecutive_failures = 0
            """,
            (device_id, timestamp, timestamp),
        )
        self._connection.commit()

    def record_success(self, device_id: str, *, attempted_at: datetime) -> None:
        timestamp = attempted_at.isoformat()
        cursor = self._connection.execute(
            """
            UPDATE collector_runtime_status
            SET heartbeat_at_utc = ?,
                stopped_at_utc = NULL,
                last_attempt_at_utc = ?,
                last_attempt_outcome = 'success',
                last_success_at_utc = ?,
                consecutive_failures = 0
            WHERE device_id = ?
            """,
            (timestamp, timestamp, timestamp, device_id),
        )
        self._require_status(cursor)
        self._connection.commit()

    def record_failure(
        self,
        device_id: str,
        *,
        attempted_at: datetime,
        category: SourceFailureCategory,
        message: str,
    ) -> None:
        timestamp = attempted_at.isoformat()
        cursor = self._connection.execute(
            """
            UPDATE collector_runtime_status
            SET heartbeat_at_utc = ?,
                stopped_at_utc = NULL,
                last_attempt_at_utc = ?,
                last_attempt_outcome = 'failure',
                last_failure_at_utc = ?,
                last_failure_category = ?,
                last_failure_message = ?,
                consecutive_failures = consecutive_failures + 1
            WHERE device_id = ?
            """,
            (timestamp, timestamp, timestamp, category.value, message, device_id),
        )
        self._require_status(cursor)
        self._connection.commit()

    def stop(self, device_id: str, *, stopped_at: datetime) -> None:
        timestamp = stopped_at.isoformat()
        cursor = self._connection.execute(
            """
            UPDATE collector_runtime_status
            SET heartbeat_at_utc = ?, stopped_at_utc = ?
            WHERE device_id = ?
            """,
            (timestamp, timestamp, device_id),
        )
        self._require_status(cursor)
        self._connection.commit()

    def latest(self, device_id: str) -> CollectorRuntimeStatus | None:
        row = self._connection.execute(
            """
            SELECT device_id, process_started_at_utc, heartbeat_at_utc, stopped_at_utc,
                   last_attempt_at_utc, last_attempt_outcome, last_success_at_utc,
                   last_failure_at_utc, last_failure_category, last_failure_message,
                   consecutive_failures
            FROM collector_runtime_status
            WHERE device_id = ?
            """,
            (device_id,),
        ).fetchone()
        return None if row is None else _status_from_row(row)

    @staticmethod
    def _require_status(cursor: sqlite3.Cursor) -> None:
        if cursor.rowcount != 1:
            raise sqlite3.DatabaseError("collector status was not initialized")


def _status_from_row(row: sqlite3.Row) -> CollectorRuntimeStatus:
    outcome = row["last_attempt_outcome"]
    return CollectorRuntimeStatus(
        device_id=str(row["device_id"]),
        process_started_at=datetime.fromisoformat(row["process_started_at_utc"]),
        heartbeat_at=datetime.fromisoformat(row["heartbeat_at_utc"]),
        stopped_at=_optional_datetime(row["stopped_at_utc"]),
        last_attempt_at=_optional_datetime(row["last_attempt_at_utc"]),
        last_attempt_outcome=(None if outcome is None else CollectionAttemptOutcome(str(outcome))),
        last_success_at=_optional_datetime(row["last_success_at_utc"]),
        last_failure_at=_optional_datetime(row["last_failure_at_utc"]),
        last_failure_category=row["last_failure_category"],
        last_failure_message=row["last_failure_message"],
        consecutive_failures=int(row["consecutive_failures"]),
    )


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))
