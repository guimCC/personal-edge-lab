from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from personal_edge_lab.domain.ac import CommandOutcome, CommandResult
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

REQUESTED_AT = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
COMPLETED_AT = REQUESTED_AT + timedelta(seconds=1)


def test_schema_initialization(tmp_path) -> None:
    database = tmp_path / "nested" / "telemetry.db"
    run_migrations(database)

    with sqlite3.connect(database) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "ac_command_audit" in names
    assert "idx_ac_command_device_requested" in names


def test_begin_and_complete_audit(tmp_path) -> None:
    result = CommandResult(
        outcome=CommandOutcome.TIMEOUT_UNKNOWN,
        error_category="timeout",
        error_message="timed out",
    )
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteCommandAuditRepository(database) as store:
        command_id = store.begin(
            device_id="node-1",
            command_type="set_state",
            payload_json='{"power":true}',
            requested_at=REQUESTED_AT,
        )
        pending = store.get(command_id)
        store.complete(command_id, result, completed_at=COMPLETED_AT)
        completed = store.get(command_id)

    assert pending is not None
    assert pending.outcome is CommandOutcome.PENDING
    assert pending.completed_at_utc is None
    assert completed is not None
    assert completed.outcome is CommandOutcome.TIMEOUT_UNKNOWN
    assert completed.requested_at_utc == REQUESTED_AT
    assert completed.completed_at_utc == COMPLETED_AT
    assert completed.error_category == "timeout"


def test_history_is_newest_first_and_limited(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteCommandAuditRepository(database) as store:
        for command_type in ["first", "second", "third"]:
            command_id = store.begin(
                device_id="node-1",
                command_type=command_type,
                payload_json="{}",
                requested_at=REQUESTED_AT,
            )
            store.complete(
                command_id,
                CommandResult(outcome=CommandOutcome.CONFIRMED_SUCCESS),
                completed_at=COMPLETED_AT,
            )
        rows = store.history(limit=2)

    assert [row.command_type for row in rows] == ["third", "second"]
