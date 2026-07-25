"""SQLite persistence for durable operational alerts."""

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
    AlertTransition,
    AlertType,
    EvaluatorOutcome,
)
from personal_edge_lab.domain.telemetry import (
    CollectionAttemptOutcome,
    CollectorRuntimeStatus,
    TemperatureReading,
)
from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection


class SqliteAlertRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = open_connection(database_path, timeout_seconds=timeout_seconds)

    def __enter__(self) -> SqliteAlertRepository:
        return self

    def __exit__(self, *args: object) -> None:
        if self._connection.in_transaction:
            self._connection.rollback()
        self.close()

    def close(self) -> None:
        self._connection.close()

    def begin_evaluation(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def record_evaluator_started(self, started_at: datetime) -> None:
        self._connection.execute(
            """
            INSERT INTO alert_runtime_status (
                singleton_id, last_started_at_utc, last_finished_at_utc,
                last_outcome, last_error_category, last_error_message
            ) VALUES (1, ?, NULL, NULL, NULL, NULL)
            ON CONFLICT(singleton_id) DO UPDATE SET
                last_started_at_utc = excluded.last_started_at_utc,
                last_outcome = NULL,
                last_error_category = NULL,
                last_error_message = NULL
            """,
            (started_at.isoformat(),),
        )
        self._connection.commit()

    def record_evaluator_success(self, finished_at: datetime) -> None:
        cursor = self._connection.execute(
            """
            UPDATE alert_runtime_status
            SET last_finished_at_utc = ?,
                last_outcome = 'success',
                last_error_category = NULL,
                last_error_message = NULL
            WHERE singleton_id = 1
            """,
            (finished_at.isoformat(),),
        )
        _require_row(cursor, "alert evaluator runtime was not initialized")

    def record_evaluator_failure(
        self,
        finished_at: datetime,
        *,
        category: str,
        message: str,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE alert_runtime_status
            SET last_finished_at_utc = ?,
                last_outcome = 'failure',
                last_error_category = ?,
                last_error_message = ?
            WHERE singleton_id = 1
            """,
            (finished_at.isoformat(), category, message),
        )
        _require_row(cursor, "alert evaluator runtime was not initialized")
        self._connection.commit()

    def latest_temperature(self, device_id: str) -> TemperatureReading | None:
        row = self._connection.execute(
            """
            SELECT device_id, sensor_type, received_at_utc, estimated_sample_at_utc,
                   temperature_c, raw_adc, age_ms, sample_interval_ms
            FROM temperature_readings
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return None if row is None else _reading_from_row(row)

    def collector_status(self, device_id: str) -> CollectorRuntimeStatus | None:
        row = self._connection.execute(
            """
            SELECT device_id, process_started_at_utc, heartbeat_at_utc, stopped_at_utc,
                   last_attempt_at_utc, last_attempt_outcome, last_success_at_utc,
                   last_failure_at_utc, last_failure_category, last_failure_message,
                   consecutive_failures
            FROM collector_runtime_status
            WHERE device_id = ?
            """,
            (device_id,),
        ).fetchone()
        return None if row is None else _collector_from_row(row)

    def get_state(self, device_id: str, alert_type: AlertType) -> AlertState | None:
        row = self._connection.execute(
            """
            SELECT device_id, alert_type, lifecycle, suspect_started_at_utc,
                   active_incident_id, recovered_at_utc, recovery_display_until_utc,
                   last_observed_at_utc, evidence_category, evidence_message
            FROM alert_states
            WHERE device_id = ? AND alert_type = ?
            """,
            (device_id, alert_type.value),
        ).fetchone()
        return None if row is None else _state_from_row(row)

    def save_state(self, state: AlertState) -> None:
        self._connection.execute(
            """
            INSERT INTO alert_states (
                device_id, alert_type, lifecycle, suspect_started_at_utc,
                active_incident_id, recovered_at_utc, recovery_display_until_utc,
                last_observed_at_utc, evidence_category, evidence_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, alert_type) DO UPDATE SET
                lifecycle = excluded.lifecycle,
                suspect_started_at_utc = excluded.suspect_started_at_utc,
                active_incident_id = excluded.active_incident_id,
                recovered_at_utc = excluded.recovered_at_utc,
                recovery_display_until_utc = excluded.recovery_display_until_utc,
                last_observed_at_utc = excluded.last_observed_at_utc,
                evidence_category = excluded.evidence_category,
                evidence_message = excluded.evidence_message
            """,
            (
                state.device_id,
                state.alert_type.value,
                state.lifecycle.value,
                _optional_iso(state.suspect_started_at),
                state.active_incident_id,
                _optional_iso(state.recovered_at),
                _optional_iso(state.recovery_display_until),
                state.last_observed_at.isoformat(),
                state.evidence_category,
                state.evidence_message,
            ),
        )

    def get_incident(self, incident_id: int) -> AlertIncident | None:
        row = self._connection.execute(
            """
            SELECT id, device_id, alert_type, status, suspect_started_at_utc,
                   alerting_at_utc, recovered_at_utc, last_observed_at_utc,
                   evidence_category, evidence_message
            FROM alert_incidents
            WHERE id = ?
            """,
            (incident_id,),
        ).fetchone()
        return None if row is None else _incident_from_row(row)

    def create_incident(
        self,
        *,
        device_id: str,
        alert_type: AlertType,
        suspect_started_at: datetime,
        alerting_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> AlertIncident:
        cursor = self._connection.execute(
            """
            INSERT INTO alert_incidents (
                device_id, alert_type, status, suspect_started_at_utc,
                alerting_at_utc, recovered_at_utc, last_observed_at_utc,
                evidence_category, evidence_message
            ) VALUES (?, ?, 'active', ?, ?, NULL, ?, ?, ?)
            """,
            (
                device_id,
                alert_type.value,
                suspect_started_at.isoformat(),
                alerting_at.isoformat(),
                alerting_at.isoformat(),
                evidence_category,
                evidence_message,
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("SQLite did not return an alert incident ID")
        incident = self.get_incident(cursor.lastrowid)
        if incident is None:
            raise sqlite3.DatabaseError("created alert incident was not found")
        return incident

    def update_incident_observation(
        self,
        incident_id: int,
        *,
        observed_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE alert_incidents
            SET last_observed_at_utc = ?,
                evidence_category = ?,
                evidence_message = ?
            WHERE id = ? AND status = 'active'
            """,
            (
                observed_at.isoformat(),
                evidence_category,
                evidence_message,
                incident_id,
            ),
        )
        _require_row(cursor, "active alert incident was not found")

    def recover_incident(
        self,
        incident_id: int,
        *,
        recovered_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> AlertIncident:
        cursor = self._connection.execute(
            """
            UPDATE alert_incidents
            SET status = 'recovered',
                recovered_at_utc = ?,
                last_observed_at_utc = ?,
                evidence_category = ?,
                evidence_message = ?
            WHERE id = ? AND status = 'active'
            """,
            (
                recovered_at.isoformat(),
                recovered_at.isoformat(),
                evidence_category,
                evidence_message,
                incident_id,
            ),
        )
        _require_row(cursor, "active alert incident was not found")
        incident = self.get_incident(incident_id)
        if incident is None:
            raise sqlite3.DatabaseError("recovered alert incident was not found")
        return incident

    def append_transition(
        self,
        *,
        incident_id: int | None,
        device_id: str,
        alert_type: AlertType,
        from_state: AlertLifecycleState,
        to_state: AlertLifecycleState,
        transitioned_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> AlertTransition:
        cursor = self._connection.execute(
            """
            INSERT INTO alert_transition_events (
                incident_id, device_id, alert_type, from_state, to_state,
                transitioned_at_utc, evidence_category, evidence_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                device_id,
                alert_type.value,
                from_state.value,
                to_state.value,
                transitioned_at.isoformat(),
                evidence_category,
                evidence_message,
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("SQLite did not return an alert transition ID")
        return AlertTransition(
            id=cursor.lastrowid,
            incident_id=incident_id,
            device_id=device_id,
            alert_type=alert_type,
            from_state=from_state,
            to_state=to_state,
            transitioned_at=transitioned_at,
            evidence_category=evidence_category,
            evidence_message=evidence_message,
        )

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
        if status is None:
            rows = self._connection.execute(
                """
                SELECT id, device_id, alert_type, status, suspect_started_at_utc,
                       alerting_at_utc, recovered_at_utc, last_observed_at_utc,
                       evidence_category, evidence_message
                FROM alert_incidents
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, limit),
            )
        else:
            rows = self._connection.execute(
                """
                SELECT id, device_id, alert_type, status, suspect_started_at_utc,
                       alerting_at_utc, recovered_at_utc, last_observed_at_utc,
                       evidence_category, evidence_message
                FROM alert_incidents
                WHERE device_id = ? AND status = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, status.value, limit),
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


def _reading_from_row(row: sqlite3.Row) -> TemperatureReading:
    return TemperatureReading(
        device_id=str(row["device_id"]),
        sensor=str(row["sensor_type"]),
        received_at=datetime.fromisoformat(row["received_at_utc"]),
        estimated_sample_at=datetime.fromisoformat(row["estimated_sample_at_utc"]),
        temperature_c=float(row["temperature_c"]),
        raw_adc=int(row["raw_adc"]),
        age_ms=int(row["age_ms"]),
        sample_interval_ms=int(row["sample_interval_ms"]),
    )


def _collector_from_row(row: sqlite3.Row) -> CollectorRuntimeStatus:
    outcome = row["last_attempt_outcome"]
    return CollectorRuntimeStatus(
        device_id=str(row["device_id"]),
        process_started_at=datetime.fromisoformat(row["process_started_at_utc"]),
        heartbeat_at=datetime.fromisoformat(row["heartbeat_at_utc"]),
        stopped_at=_optional_datetime(row["stopped_at_utc"]),
        last_attempt_at=_optional_datetime(row["last_attempt_at_utc"]),
        last_attempt_outcome=(None if outcome is None else CollectionAttemptOutcome(str(outcome))),
        last_success_at=_optional_datetime(row["last_success_at_utc"]),
        last_failure_at=_optional_datetime(row["last_failure_at_utc"]),
        last_failure_category=row["last_failure_category"],
        last_failure_message=row["last_failure_message"],
        consecutive_failures=int(row["consecutive_failures"]),
    )


def _optional_iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _require_row(cursor: sqlite3.Cursor, message: str) -> None:
    if cursor.rowcount != 1:
        raise sqlite3.DatabaseError(message)
