"""SQLite AC command-audit repository."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from personal_edge_lab.domain.ac import (
    CommandAuditEntry,
    CommandOutcome,
    CommandResult,
)


class SqliteCommandAuditRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = sqlite3.connect(database_path, timeout=timeout_seconds)
        self._connection.row_factory = sqlite3.Row

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
                requested_at_utc, outcome
            ) VALUES (?, ?, ?, ?, ?)
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
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("SQLite did not return an inserted command ID")
        return cursor.lastrowid

    def complete(self, command_id: int, result: CommandResult) -> None:
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
        self._connection.commit()
        if cursor.rowcount != 1:
            raise sqlite3.DatabaseError(f"command audit record {command_id} was not found")

    def history(self, *, limit: int) -> list[CommandAuditEntry]:
        rows = self._connection.execute(
            """
            SELECT id, device_id, command_type, command_payload_json,
                   requested_at_utc, completed_at_utc, outcome, http_status,
                   response_body, error_category, error_message
            FROM ac_command_audit
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


def _entry_from_row(row: sqlite3.Row) -> CommandAuditEntry:
    completed = row["completed_at_utc"]
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
    )
