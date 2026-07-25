from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from personal_edge_lab.apps.alert_evaluator.__main__ import main

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)


def test_alert_evaluator_runs_once_without_network_or_existing_data(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "alerts.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("DEVICE_ID", "node-1")

    assert main(clock=lambda: NOW) == 0

    with sqlite3.connect(database) as connection:
        runtime = connection.execute(
            """
            SELECT last_outcome, last_finished_at_utc
            FROM alert_runtime_status
            WHERE singleton_id = 1
            """
        ).fetchone()
        states = connection.execute(
            """
            SELECT alert_type, lifecycle
            FROM alert_states
            ORDER BY alert_type
            """
        ).fetchall()
        commands = connection.execute("SELECT COUNT(*) FROM ac_command_audit").fetchone()
        telemetry = connection.execute("SELECT COUNT(*) FROM temperature_readings").fetchone()

    assert runtime == ("success", NOW.isoformat())
    assert states == [
        ("edge_unavailable", "healthy"),
        ("telemetry_stale", "suspect"),
    ]
    assert commands == (0,)
    assert telemetry == (0,)


def test_alert_evaluator_rejects_invalid_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "alerts.db"))
    monkeypatch.setenv("ALERT_TELEMETRY_ALERT_AFTER_SECONDS", "30")

    assert main(clock=lambda: NOW) == 2
