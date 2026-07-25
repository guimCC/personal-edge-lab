from __future__ import annotations

import sqlite3

from ac_control.models import CommandOutcome, CommandResult
from ac_control.storage import CommandAuditStore


def test_schema_initialization(tmp_path) -> None:
    database = tmp_path / "nested" / "telemetry.db"
    with CommandAuditStore(database):
        pass

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
    with CommandAuditStore(tmp_path / "telemetry.db") as store:
        command_id = store.begin(
            device_id="node-1",
            command_type="set_state",
            payload_json='{"power":true}',
        )
        pending = store.get(command_id)
        store.complete(command_id, result)
        completed = store.get(command_id)

    assert pending is not None
    assert pending["outcome"] == "pending"
    assert pending["completed_at_utc"] is None
    assert completed is not None
    assert completed["outcome"] == "timeout_unknown"
    assert completed["completed_at_utc"] is not None
    assert completed["error_category"] == "timeout"


def test_history_is_newest_first_and_limited(tmp_path) -> None:
    with CommandAuditStore(tmp_path / "telemetry.db") as store:
        for command_type in ["first", "second", "third"]:
            command_id = store.begin(
                device_id="node-1",
                command_type=command_type,
                payload_json="{}",
            )
            store.complete(
                command_id,
                CommandResult(outcome=CommandOutcome.CONFIRMED_SUCCESS),
            )
        rows = store.history(limit=2)

    assert [row["command_type"] for row in rows] == ["third", "second"]
