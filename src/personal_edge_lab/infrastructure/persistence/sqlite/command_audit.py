"""SQLite AC command-audit repository."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path

from personal_edge_lab.domain.ac import (
    CommandAuditEntry,
    CommandOutcome,
    CommandRequestContext,
    CommandReservation,
    CommandReservationStatus,
    CommandResult,
)


class SqliteCommandAuditRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = sqlite3.connect(database_path, timeout=timeout_seconds)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")

    def __enter__(self) -> SqliteCommandAuditRepository:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def begin(self, *, device_id: str, command_type: str, payload_json: str) -> int:
        cursor = self._connection.execute(
            """
            INSERT INTO ac_command_audit (
                device_id, command_type, command_payload_json,
                requested_at_utc, outcome, request_source
            ) VALUES (?, ?, ?, ?, ?, 'local_cli')
            """,
            (
                device_id,
                command_type,
                payload_json,
                datetime.now(UTC).isoformat(),
                CommandOutcome.PENDING.value,
            ),
        )
        self._connection.commit()
        return _lastrowid(cursor)

    def reserve(
        self,
        *,
        device_id: str,
        command_type: str,
        payload_json: str,
        request_fingerprint: str,
        context: CommandRequestContext,
        requested_at: datetime,
        requires_device_lock: bool,
    ) -> CommandReservation:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                """
                SELECT * FROM ac_command_audit
                WHERE actor_id = ? AND idempotency_key = ?
                """,
                (context.actor_id, context.idempotency_key),
            ).fetchone()
            if existing is not None:
                entry = _entry_from_row(existing)
                if entry.request_fingerprint != request_fingerprint:
                    self._connection.commit()
                    return CommandReservation(CommandReservationStatus.CONFLICT, entry=entry)
                if entry.outcome is CommandOutcome.PENDING:
                    lock = self._connection.execute(
                        """
                        SELECT lease_expires_at_utc
                        FROM ac_command_device_locks
                        WHERE command_id = ?
                        """,
                        (entry.id,),
                    ).fetchone()
                    if lock is not None and requested_at >= datetime.fromisoformat(
                        lock["lease_expires_at_utc"]
                    ):
                        self._recover_interrupted(entry.id, requested_at)
                        self._connection.execute(
                            "DELETE FROM ac_command_device_locks WHERE command_id = ?",
                            (entry.id,),
                        )
                        recovered = self._connection.execute(
                            "SELECT * FROM ac_command_audit WHERE id = ?",
                            (entry.id,),
                        ).fetchone()
                        if recovered is None:
                            raise sqlite3.DatabaseError(
                                f"command audit record {entry.id} was not found"
                            )
                        entry = _entry_from_row(recovered)
                        self._connection.commit()
                        return CommandReservation(
                            CommandReservationStatus.REPLAYED,
                            command_id=entry.id,
                            entry=entry,
                        )
                self._connection.commit()
                status = (
                    CommandReservationStatus.IN_PROGRESS
                    if entry.outcome is CommandOutcome.PENDING
                    else CommandReservationStatus.REPLAYED
                )
                return CommandReservation(status, command_id=entry.id, entry=entry)

            rate_since = requested_at - timedelta(seconds=context.rate_window_seconds)
            recent_count = int(
                self._connection.execute(
                    """
                    SELECT COUNT(*) FROM ac_command_audit
                    WHERE actor_id = ? AND requested_at_utc >= ?
                    """,
                    (context.actor_id, rate_since.isoformat()),
                ).fetchone()[0]
            )
            if recent_count >= context.rate_limit:
                oldest = self._connection.execute(
                    """
                    SELECT requested_at_utc FROM ac_command_audit
                    WHERE actor_id = ? AND requested_at_utc >= ?
                    ORDER BY requested_at_utc ASC LIMIT 1
                    """,
                    (context.actor_id, rate_since.isoformat()),
                ).fetchone()
                retry_after = context.rate_window_seconds
                if oldest is not None:
                    retry_at = datetime.fromisoformat(oldest[0]) + timedelta(
                        seconds=context.rate_window_seconds
                    )
                    retry_after = max(
                        1,
                        ceil((retry_at - requested_at).total_seconds()),
                    )
                self._connection.commit()
                return CommandReservation(
                    CommandReservationStatus.RATE_LIMITED,
                    retry_after_seconds=retry_after,
                )

            if requires_device_lock:
                lock = self._connection.execute(
                    "SELECT * FROM ac_command_device_locks WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
                if lock is not None:
                    lease_expiry = datetime.fromisoformat(lock["lease_expires_at_utc"])
                    if requested_at >= lease_expiry:
                        self._recover_interrupted(int(lock["command_id"]), requested_at)
                        self._connection.execute(
                            "DELETE FROM ac_command_device_locks WHERE device_id = ?",
                            (device_id,),
                        )
                    else:
                        self._connection.commit()
                        return CommandReservation(CommandReservationStatus.DEVICE_BUSY)

            cursor = self._connection.execute(
                """
                INSERT INTO ac_command_audit (
                    device_id, command_type, command_payload_json,
                    requested_at_utc, outcome, actor_id, request_source,
                    idempotency_key, request_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    command_type,
                    payload_json,
                    requested_at.isoformat(),
                    CommandOutcome.PENDING.value,
                    context.actor_id,
                    context.request_source,
                    context.idempotency_key,
                    request_fingerprint,
                ),
            )
            command_id = _lastrowid(cursor)
            if requires_device_lock:
                lease_expiry = requested_at + timedelta(seconds=context.lock_lease_seconds)
                self._connection.execute(
                    """
                    INSERT INTO ac_command_device_locks (
                        device_id, command_id, lease_expires_at_utc
                    ) VALUES (?, ?, ?)
                    """,
                    (device_id, command_id, lease_expiry.isoformat()),
                )
            self._connection.commit()
            return CommandReservation(CommandReservationStatus.NEW, command_id=command_id)
        except BaseException:
            self._connection.rollback()
            raise

    def complete(self, command_id: int, result: CommandResult) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE ac_command_audit
                SET completed_at_utc = ?, outcome = ?, http_status = ?,
                    response_body = ?, error_category = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    datetime.now(UTC).isoformat(),
                    result.outcome.value,
                    result.http_status,
                    result.response_body,
                    result.error_category,
                    result.error_message,
                    command_id,
                ),
            )
            if cursor.rowcount != 1:
                raise sqlite3.DatabaseError(f"command audit record {command_id} was not found")
            self._connection.execute(
                "DELETE FROM ac_command_device_locks WHERE command_id = ?",
                (command_id,),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def history(self, *, limit: int) -> list[CommandAuditEntry]:
        rows = self._connection.execute(
            """
            SELECT * FROM ac_command_audit
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_entry_from_row(row) for row in rows]

    def get(self, command_id: int) -> CommandAuditEntry | None:
        row = self._connection.execute(
            "SELECT * FROM ac_command_audit WHERE id = ?",
            (command_id,),
        ).fetchone()
        return None if row is None else _entry_from_row(row)

    def _recover_interrupted(self, command_id: int, recovered_at: datetime) -> None:
        self._connection.execute(
            """
            UPDATE ac_command_audit
            SET completed_at_utc = ?, outcome = ?, error_category = ?,
                error_message = ?
            WHERE id = ? AND outcome = ?
            """,
            (
                recovered_at.isoformat(),
                CommandOutcome.RESPONSE_UNKNOWN.value,
                "interrupted_unknown",
                "command processing was interrupted; physical outcome is unknown",
                command_id,
                CommandOutcome.PENDING.value,
            ),
        )


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("SQLite did not return an inserted command ID")
    return int(cursor.lastrowid)


def _entry_from_row(row: sqlite3.Row) -> CommandAuditEntry:
    completed = row["completed_at_utc"]
    columns = set(row.keys())
    return CommandAuditEntry(
        id=int(row["id"]),
        device_id=str(row["device_id"]),
        command_type=str(row["command_type"]),
        command_payload_json=str(row["command_payload_json"]),
        requested_at_utc=datetime.fromisoformat(row["requested_at_utc"]),
        completed_at_utc=None if completed is None else datetime.fromisoformat(completed),
        outcome=CommandOutcome(row["outcome"]),
        http_status=None if row["http_status"] is None else int(row["http_status"]),
        response_body=row["response_body"],
        error_category=row["error_category"],
        error_message=row["error_message"],
        actor_id=row["actor_id"] if "actor_id" in columns else None,
        request_source=(str(row["request_source"]) if "request_source" in columns else "local_cli"),
        idempotency_key=row["idempotency_key"] if "idempotency_key" in columns else None,
        request_fingerprint=(
            row["request_fingerprint"] if "request_fingerprint" in columns else None
        ),
    )
