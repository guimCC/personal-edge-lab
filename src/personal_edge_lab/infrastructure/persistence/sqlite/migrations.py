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
    Migration(
        version="003_authenticated_control",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                csrf_token TEXT NOT NULL,
                credential_fingerprint TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                last_seen_at_utc TEXT NOT NULL,
                idle_expires_at_utc TEXT NOT NULL,
                absolute_expires_at_utc TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
            ON auth_sessions (idle_expires_at_utc, absolute_expires_at_utc)
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_login_throttle (
                actor_id TEXT PRIMARY KEY,
                window_started_at_utc TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL
                    CHECK (failed_attempts >= 0),
                blocked_until_utc TEXT
            )
            """,
            "ALTER TABLE ac_command_audit ADD COLUMN actor_id TEXT",
            """
            ALTER TABLE ac_command_audit
            ADD COLUMN request_source TEXT NOT NULL DEFAULT 'local_cli'
            """,
            "ALTER TABLE ac_command_audit ADD COLUMN idempotency_key TEXT",
            "ALTER TABLE ac_command_audit ADD COLUMN request_fingerprint TEXT",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ac_command_actor_idempotency
            ON ac_command_audit (actor_id, idempotency_key)
            WHERE actor_id IS NOT NULL AND idempotency_key IS NOT NULL
            """,
            """
            CREATE TABLE IF NOT EXISTS ac_command_device_locks (
                device_id TEXT PRIMARY KEY,
                command_id INTEGER NOT NULL,
                lease_expires_at_utc TEXT NOT NULL,
                FOREIGN KEY (command_id) REFERENCES ac_command_audit (id)
            )
            """,
        ),
    ),
    Migration(
        version="004_operational_alerts",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS alert_runtime_status (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                last_started_at_utc TEXT NOT NULL,
                last_finished_at_utc TEXT,
                last_outcome TEXT,
                last_error_category TEXT,
                last_error_message TEXT,
                CHECK (last_outcome IS NULL OR last_outcome IN ('success', 'failure'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                status TEXT NOT NULL
                    CHECK (status IN ('active', 'recovered')),
                suspect_started_at_utc TEXT NOT NULL,
                alerting_at_utc TEXT NOT NULL,
                recovered_at_utc TEXT,
                last_observed_at_utc TEXT NOT NULL,
                evidence_category TEXT NOT NULL,
                evidence_message TEXT NOT NULL,
                CHECK (
                    recovered_at_utc IS NULL
                    OR recovered_at_utc >= alerting_at_utc
                ),
                CHECK (last_observed_at_utc >= suspect_started_at_utc)
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_one_active_incident
            ON alert_incidents (device_id, alert_type)
            WHERE status = 'active'
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_alert_incident_device_newest
            ON alert_incidents (device_id, id DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_states (
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                lifecycle TEXT NOT NULL
                    CHECK (lifecycle IN ('healthy', 'suspect', 'alerting', 'recovered')),
                suspect_started_at_utc TEXT,
                active_incident_id INTEGER,
                recovered_at_utc TEXT,
                recovery_display_until_utc TEXT,
                last_observed_at_utc TEXT NOT NULL,
                evidence_category TEXT NOT NULL,
                evidence_message TEXT NOT NULL,
                PRIMARY KEY (device_id, alert_type),
                FOREIGN KEY (active_incident_id) REFERENCES alert_incidents (id),
                CHECK (
                    lifecycle != 'alerting'
                    OR active_incident_id IS NOT NULL
                ),
                CHECK (
                    lifecycle != 'suspect'
                    OR suspect_started_at_utc IS NOT NULL
                ),
                CHECK (
                    lifecycle != 'recovered'
                    OR (
                        recovered_at_utc IS NOT NULL
                        AND recovery_display_until_utc IS NOT NULL
                    )
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_transition_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL
                    CHECK (alert_type IN ('telemetry_stale', 'edge_unavailable')),
                from_state TEXT NOT NULL
                    CHECK (from_state IN ('healthy', 'suspect', 'alerting', 'recovered')),
                to_state TEXT NOT NULL
                    CHECK (to_state IN ('healthy', 'suspect', 'alerting', 'recovered')),
                transitioned_at_utc TEXT NOT NULL,
                evidence_category TEXT NOT NULL,
                evidence_message TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES alert_incidents (id),
                CHECK (from_state != to_state)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_alert_transition_device_newest
            ON alert_transition_events (device_id, id DESC)
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
