"""Small transactional SQLite migration runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    statements: Sequence[str]


MIGRATIONS = (
    Migration(
        version="001_initial",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS temperature_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                received_at_utc TEXT NOT NULL,
                estimated_sample_at_utc TEXT NOT NULL,
                temperature_c REAL NOT NULL,
                raw_adc INTEGER NOT NULL,
                age_ms INTEGER NOT NULL,
                sample_interval_ms INTEGER NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_temperature_device_received
            ON temperature_readings (device_id, received_at_utc)
            """,
            """
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
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ac_command_device_requested
            ON ac_command_audit (device_id, requested_at_utc)
            """,
        ),
    ),
    Migration(
        version="002_collector_runtime_status",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS collector_runtime_status (
                device_id TEXT PRIMARY KEY,
                process_started_at_utc TEXT NOT NULL,
                heartbeat_at_utc TEXT NOT NULL,
                stopped_at_utc TEXT,
                last_attempt_at_utc TEXT,
                last_attempt_outcome TEXT,
                last_success_at_utc TEXT,
                last_failure_at_utc TEXT,
                last_failure_category TEXT,
                last_failure_message TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0
                    CHECK (consecutive_failures >= 0),
                CHECK (
                    last_attempt_outcome IS NULL
                    OR last_attempt_outcome IN ('success', 'failure')
                )
            )
            """,
        ),
    ),
)


def run_migrations(
    database_path: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Apply pending migrations atomically, preserving compatible existing tables."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path, timeout=timeout_seconds) as connection:
        connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
                """
            )
            applied = {
                str(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, applied_at_utc)
                    VALUES (?, ?)
                    """,
                    (migration.version, datetime.now(UTC).isoformat()),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
