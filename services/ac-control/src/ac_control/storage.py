"""SQLite command-audit persistence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ac_control.models import CommandOutcome, CommandResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_command_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    command_payload_json TEXT NOT NULL,
    requested_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    outcome TEXT NOT NULL,
    http_status INTEGER,
    response_body TEXT,
    error_category TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_ac_command_device_requested
ON ac_command_audit (device_id, requested_at_utc);
"""


class CommandAuditStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def __enter__(self) -> CommandAuditStore:
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

    def history(self, *, limit: int) -> list[sqlite3.Row]:
        return list(
            self._connection.execute(
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
        )

    def get(self, command_id: int) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM ac_command_audit WHERE id = ?",
            (command_id,),
        ).fetchone()
