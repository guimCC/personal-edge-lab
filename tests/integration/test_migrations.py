from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

from personal_edge_lab.infrastructure.persistence.sqlite.migrations import (
    MIGRATIONS,
    run_migrations,
)


def object_names(database) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }


def test_migration_builds_complete_schema_on_empty_database(tmp_path) -> None:
    database = tmp_path / "empty.db"
    run_migrations(database)

    assert {
        "schema_migrations",
        "temperature_readings",
        "idx_temperature_device_received",
        "ac_command_audit",
        "idx_ac_command_device_requested",
        "collector_runtime_status",
        "auth_sessions",
        "idx_auth_sessions_expiry",
        "auth_login_throttle",
        "idx_ac_command_actor_idempotency",
        "ac_command_device_locks",
        "alert_runtime_status",
        "alert_states",
        "alert_incidents",
        "idx_alert_one_active_incident",
        "idx_alert_incident_device_newest",
        "alert_transition_events",
        "idx_alert_transition_device_newest",
        "notification_policy",
        "notification_outbox",
        "idx_notification_outbox_due",
        "idx_notification_outbox_alert_flapping",
        "notification_delivery_runtime",
        "email_triage_runs",
        "idx_email_triage_runs_recent",
        "email_triage_evaluations",
        "email_triage_run_items",
        "idx_email_triage_items_evaluation",
        "email_triage_attempts",
        "idx_email_triage_one_active_attempt",
        "idx_email_triage_attempts_run",
        "email_triage_messages",
        "idx_email_triage_messages_recent",
        "idx_email_triage_messages_status",
        "email_triage_content_snapshots",
        "email_triage_evaluation_content",
        "idx_email_triage_items_message",
        "email_triage_feedback",
        "idx_email_triage_feedback_latest",
        "idx_email_triage_feedback_sync",
        "email_triage_backfill_jobs",
        "idx_email_triage_one_active_backfill",
        "idx_email_triage_backfill_jobs_recent",
        "email_triage_backfill_segments",
        "email_triage_backfill_items",
        "idx_email_triage_backfill_items_pending",
    } <= object_names(database)
    with sqlite3.connect(database) as connection:
        versions = list(connection.execute("SELECT version FROM schema_migrations"))
    assert versions == [
        ("001_initial",),
        ("002_collector_runtime_status",),
        ("003_authenticated_control",),
        ("004_operational_alerts",),
        ("005_notification_outbox",),
        ("006_email_triage_runs",),
        ("007_email_triage_messages",),
        ("008_email_triage_taxonomy_v2",),
        ("009_email_triage_feedback",),
        ("010_email_triage_backfill",),
    ]


def test_migration_preserves_existing_tables_rows_and_indexes(tmp_path) -> None:
    database = tmp_path / "existing.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE temperature_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                received_at_utc TEXT NOT NULL,
                estimated_sample_at_utc TEXT NOT NULL,
                temperature_c REAL NOT NULL,
                raw_adc INTEGER NOT NULL,
                age_ms INTEGER NOT NULL,
                sample_interval_ms INTEGER NOT NULL
            );
            CREATE INDEX idx_temperature_device_received
            ON temperature_readings (device_id, received_at_utc);
            CREATE TABLE ac_command_audit (
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
            CREATE INDEX idx_ac_command_device_requested
            ON ac_command_audit (device_id, requested_at_utc);
            INSERT INTO temperature_readings VALUES (
                7, 'node-1', 'thermistor', '2026-07-21T12:00:00+00:00',
                '2026-07-21T11:59:59.500000+00:00', 21.5, 1700, 500, 2000
            );
            INSERT INTO ac_command_audit VALUES (
                9, 'node-1', 'power_off', '{"power":false}',
                '2026-07-21T12:01:00+00:00', '2026-07-21T12:01:01+00:00',
                'confirmed_success', 200, '{}', NULL, NULL
            );
            """
        )

    before_names = object_names(database)
    run_migrations(database)

    with sqlite3.connect(database) as connection:
        telemetry = connection.execute(
            "SELECT id, temperature_c FROM temperature_readings"
        ).fetchall()
        commands = connection.execute("SELECT id, outcome FROM ac_command_audit").fetchall()
    assert telemetry == [(7, 21.5)]
    assert commands == [(9, "confirmed_success")]
    assert before_names <= object_names(database)


def test_message_migration_preserves_existing_triage_evidence(tmp_path) -> None:
    database = tmp_path / "wp7.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at_utc TEXT NOT NULL
            )
            """
        )
        for migration in MIGRATIONS[:-1]:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at_utc) VALUES (?, ?)",
                (migration.version, "2026-07-28T12:00:00+00:00"),
            )
        connection.execute(
            """
            INSERT INTO email_triage_runs (
                run_id, operation_id, query_sha256, requested_limit,
                force_new_attempt, status, requested_at_utc, updated_at_utc,
                completed_at_utc
            ) VALUES (
                'accepted-wp7-run', 'accepted-wp7-operation', ?, 1, 0,
                'completed_with_results', '2026-07-28T12:00:00+00:00',
                '2026-07-28T12:01:00+00:00', '2026-07-28T12:01:00+00:00'
            )
            """,
            ("f" * 64,),
        )

    run_migrations(database)

    with sqlite3.connect(database) as connection:
        preserved = connection.execute(
            "SELECT run_id, status, query_text FROM email_triage_runs"
        ).fetchone()
        version = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = '007_email_triage_messages'"
        ).fetchone()
    assert preserved == ("accepted-wp7-run", "completed_with_results", None)
    assert version == (1,)


def test_concurrent_app_startup_applies_migration_once(tmp_path) -> None:
    database = tmp_path / "race.db"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: run_migrations(database), range(8)))

    with sqlite3.connect(database) as connection:
        migration_counts = connection.execute(
            "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version ORDER BY version"
        ).fetchall()
    assert migration_counts == [
        ("001_initial", 1),
        ("002_collector_runtime_status", 1),
        ("003_authenticated_control", 1),
        ("004_operational_alerts", 1),
        ("005_notification_outbox", 1),
        ("006_email_triage_runs", 1),
        ("007_email_triage_messages", 1),
        ("008_email_triage_taxonomy_v2", 1),
        ("009_email_triage_feedback", 1),
        ("010_email_triage_backfill", 1),
    ]
