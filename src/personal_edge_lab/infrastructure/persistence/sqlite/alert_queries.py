"""SQLite read-only queries for durable operational alerts."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from personal_edge_lab.domain.alerting import (
    AlertEvaluatorRuntime,
    AlertIncident,
    AlertIncidentStatus,
    AlertLifecycleState,
    AlertState,
    AlertType,
    EvaluatorOutcome,
)
from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection


class SqliteAlertQueryRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = open_connection(database_path, timeout_seconds=timeout_seconds)

    def __enter__(self) -> SqliteAlertQueryRepository:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def states(self, device_id: str) -> list[AlertState]:
        rows = self._connection.execute(
            """
            SELECT device_id, alert_type, lifecycle, suspect_started_at_utc,
                   active_incident_id, recovered_at_utc, recovery_display_until_utc,
                   last_observed_at_utc, evidence_category, evidence_message
            FROM alert_states
            WHERE device_id = ?
            ORDER BY alert_type
            """,
            (device_id,),
        )
        return [_state_from_row(row) for row in rows]

    def incidents(
        self,
        device_id: str,
        *,
        status: AlertIncidentStatus | None,
        limit: int,
    ) -> list[AlertIncident]:
        status_clause = "" if status is None else " AND status = ?"
        parameters: tuple[object, ...] = (
            (device_id, limit) if status is None else (device_id, status.value, limit)
        )
        rows = self._connection.execute(
            f"""
            SELECT id, device_id, alert_type, status, suspect_started_at_utc,
                   alerting_at_utc, recovered_at_utc, last_observed_at_utc,
                   evidence_category, evidence_message
            FROM alert_incidents
            WHERE device_id = ?{status_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            parameters,
        )
        return [_incident_from_row(row) for row in rows]

    def evaluator_runtime(self) -> AlertEvaluatorRuntime | None:
        row = self._connection.execute(
            """
            SELECT last_started_at_utc, last_finished_at_utc, last_outcome,
                   last_error_category, last_error_message
            FROM alert_runtime_status
            WHERE singleton_id = 1
            """
        ).fetchone()
        return None if row is None else _runtime_from_row(row)

    def latest_transition_at(self, device_id: str) -> datetime | None:
        row = self._connection.execute(
            """
            SELECT transitioned_at_utc
            FROM alert_transition_events
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return None if row is None else datetime.fromisoformat(row["transitioned_at_utc"])


def _state_from_row(row: sqlite3.Row) -> AlertState:
    return AlertState(
        device_id=str(row["device_id"]),
        alert_type=AlertType(str(row["alert_type"])),
        lifecycle=AlertLifecycleState(str(row["lifecycle"])),
        suspect_started_at=_optional_datetime(row["suspect_started_at_utc"]),
        active_incident_id=(
            None if row["active_incident_id"] is None else int(row["active_incident_id"])
        ),
        recovered_at=_optional_datetime(row["recovered_at_utc"]),
        recovery_display_until=_optional_datetime(row["recovery_display_until_utc"]),
        last_observed_at=datetime.fromisoformat(row["last_observed_at_utc"]),
        evidence_category=str(row["evidence_category"]),
        evidence_message=str(row["evidence_message"]),
    )


def _incident_from_row(row: sqlite3.Row) -> AlertIncident:
    return AlertIncident(
        id=int(row["id"]),
        device_id=str(row["device_id"]),
        alert_type=AlertType(str(row["alert_type"])),
        status=AlertIncidentStatus(str(row["status"])),
        suspect_started_at=datetime.fromisoformat(row["suspect_started_at_utc"]),
        alerting_at=datetime.fromisoformat(row["alerting_at_utc"]),
        recovered_at=_optional_datetime(row["recovered_at_utc"]),
        last_observed_at=datetime.fromisoformat(row["last_observed_at_utc"]),
        evidence_category=str(row["evidence_category"]),
        evidence_message=str(row["evidence_message"]),
    )


def _runtime_from_row(row: sqlite3.Row) -> AlertEvaluatorRuntime:
    outcome = row["last_outcome"]
    return AlertEvaluatorRuntime(
        last_started_at=datetime.fromisoformat(row["last_started_at_utc"]),
        last_finished_at=_optional_datetime(row["last_finished_at_utc"]),
        last_outcome=None if outcome is None else EvaluatorOutcome(str(outcome)),
        last_error_category=row["last_error_category"],
        last_error_message=row["last_error_message"],
    )


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))
