from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime

import pytest

from personal_edge_lab.infrastructure.persistence.sqlite.email_triage_reset import (
    RESET_CONFIRMATION,
    TriageDevelopmentResetError,
    reset_triage_development_data,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

NOW = datetime(2026, 7, 28, 16, 0, tzinfo=UTC)


def _insert_run(database, *, status: str = "completed_with_results") -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO email_triage_runs (
                run_id, operation_id, query_sha256, query_text, requested_limit,
                force_new_attempt, status, requested_at_utc, updated_at_utc,
                completed_at_utc
            ) VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?, ?)
            """,
            (
                "development-run",
                "development-operation",
                "f" * 64,
                "private development query",
                status,
                NOW.isoformat(),
                NOW.isoformat(),
                NOW.isoformat() if status.startswith("completed") else None,
            ),
        )
        connection.execute(
            """
            INSERT INTO temperature_readings (
                device_id, sensor_type, received_at_utc, estimated_sample_at_utc,
                temperature_c, raw_adc, age_ms, sample_interval_ms
            ) VALUES ('node-1', 'thermistor', ?, ?, 22.5, 1500, 0, 2000)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )


def test_reset_backs_up_and_deletes_only_triage_rows(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    _insert_run(database)

    result = reset_triage_development_data(
        database,
        confirmation=RESET_CONFIRMATION,
        now=NOW,
    )

    assert result.deleted_counts["email_triage_runs"] == 1
    assert result.backup_path.is_file()
    assert stat.S_IMODE(result.backup_path.stat().st_mode) == 0o600
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_triage_runs").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM temperature_readings").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = '007_email_triage_messages'"
        ).fetchone() == (1,)
    with sqlite3.connect(result.backup_path) as backup:
        assert backup.execute("SELECT query_text FROM email_triage_runs").fetchone() == (
            "private development query",
        )


def test_reset_requires_exact_confirmation_and_refuses_unfinished_work(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    _insert_run(database, status="classifying")

    with pytest.raises(TriageDevelopmentResetError, match="confirmation"):
        reset_triage_development_data(database, confirmation="yes", now=NOW)
    with pytest.raises(TriageDevelopmentResetError, match="unfinished"):
        reset_triage_development_data(
            database,
            confirmation=RESET_CONFIRMATION,
            now=NOW,
        )

    assert not (tmp_path / "backups").exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_triage_runs").fetchone() == (1,)


def test_reset_rolls_back_all_deletions_when_the_transaction_fails(
    tmp_path,
) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    _insert_run(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_triage_reset
            BEFORE DELETE ON email_triage_runs
            BEGIN
                SELECT RAISE(ABORT, 'test reset failure');
            END
            """
        )

    with pytest.raises(sqlite3.DatabaseError):
        reset_triage_development_data(
            database,
            confirmation=RESET_CONFIRMATION,
            now=NOW,
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_triage_runs").fetchone() == (1,)
