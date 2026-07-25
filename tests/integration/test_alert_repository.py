from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from personal_edge_lab.application.ports.telemetry import SourceFailureCategory
from personal_edge_lab.domain.alerting import (
    AlertIncidentStatus,
    AlertLifecycleState,
    AlertPolicy,
    AlertType,
    EvaluatorOutcome,
)
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.alert_evaluation import (
    SqliteAlertEvaluationRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.alert_queries import (
    SqliteAlertQueryRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.alerting import (
    AlertHistoryFilter,
    AlertStatusSummary,
    EvaluateOperationalAlerts,
    GetOperationalAlerts,
)

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
POLICY = AlertPolicy(
    telemetry_suspect_after_seconds=45,
    telemetry_alert_after_seconds=180,
    edge_min_consecutive_failures=4,
    edge_alert_after_seconds=45,
    recovery_display_seconds=300,
)


def reading(received_at: datetime) -> TemperatureReading:
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": 24.5,
            "raw_adc": 1700,
            "age_ms": 500,
            "sample_interval_ms": 2000,
        },
        device_id="node-1",
        received_at=received_at,
    )


def evaluate(database, now: datetime):
    return EvaluateOperationalAlerts(
        lambda: SqliteAlertEvaluationRepository(database),
        device_id="node-1",
        policy=POLICY,
        clock=lambda: now,
    ).execute()


def state(database, alert_type: AlertType):
    with SqliteAlertEvaluationRepository(database) as repository:
        return repository.get_state("node-1", alert_type)


def test_telemetry_boundaries_deduplicate_and_recover(tmp_path) -> None:
    database = tmp_path / "alerts.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW - timedelta(seconds=45)))

    result = evaluate(database, NOW)
    assert state(database, AlertType.TELEMETRY_STALE).lifecycle is AlertLifecycleState.HEALTHY
    assert result.transitions == ()

    stale_at = NOW + timedelta(milliseconds=1)
    evaluate(database, stale_at)
    assert state(database, AlertType.TELEMETRY_STALE).lifecycle is AlertLifecycleState.SUSPECT

    exact_alert_boundary = NOW + timedelta(seconds=135)
    evaluate(database, exact_alert_boundary)
    assert state(database, AlertType.TELEMETRY_STALE).lifecycle is AlertLifecycleState.SUSPECT

    alert_at = exact_alert_boundary + timedelta(milliseconds=1)
    evaluate(database, alert_at)
    active = state(database, AlertType.TELEMETRY_STALE)
    assert active.lifecycle is AlertLifecycleState.ALERTING
    assert active.active_incident_id is not None

    evaluate(database, alert_at + timedelta(seconds=30))
    with SqliteAlertQueryRepository(database) as repository:
        incidents = repository.incidents(
            "node-1",
            status=AlertIncidentStatus.ACTIVE,
            limit=10,
        )
    assert len(incidents) == 1

    recovered_at = alert_at + timedelta(seconds=45)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(recovered_at))
    evaluate(database, recovered_at)
    recovered = state(database, AlertType.TELEMETRY_STALE)
    assert recovered.lifecycle is AlertLifecycleState.RECOVERED

    healthy_at = recovered_at + timedelta(seconds=300)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(healthy_at))
    evaluate(database, healthy_at)
    assert state(database, AlertType.TELEMETRY_STALE).lifecycle is AlertLifecycleState.HEALTHY


def test_edge_requires_failure_count_and_sustained_time_then_recovers(tmp_path) -> None:
    database = tmp_path / "edge-alert.db"
    run_migrations(database)
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(minutes=1))
        repository.record_failure(
            "node-1",
            attempted_at=NOW,
            category=SourceFailureCategory.TIMEOUT,
            message="temperature request timed out",
        )

    evaluate(database, NOW)
    assert state(database, AlertType.EDGE_UNAVAILABLE).lifecycle is AlertLifecycleState.SUSPECT

    with SqliteCollectorStatusRepository(database) as repository:
        for seconds in (15, 30, 45):
            repository.record_failure(
                "node-1",
                attempted_at=NOW + timedelta(seconds=seconds),
                category=SourceFailureCategory.TIMEOUT,
                message="temperature request timed out",
            )

    evaluate(database, NOW + timedelta(seconds=44, milliseconds=999))
    assert state(database, AlertType.EDGE_UNAVAILABLE).lifecycle is AlertLifecycleState.SUSPECT

    alert_at = NOW + timedelta(seconds=45)
    evaluate(database, alert_at)
    assert state(database, AlertType.EDGE_UNAVAILABLE).lifecycle is AlertLifecycleState.ALERTING

    with SqliteCollectorStatusRepository(database) as repository:
        repository.record_success("node-1", attempted_at=alert_at + timedelta(seconds=15))
    evaluate(database, alert_at + timedelta(seconds=15))
    assert state(database, AlertType.EDGE_UNAVAILABLE).lifecycle is AlertLifecycleState.RECOVERED


def test_stale_collector_does_not_create_or_recover_edge_incident(tmp_path) -> None:
    database = tmp_path / "unknown-edge.db"
    run_migrations(database)
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(minutes=5))
        repository.record_failure(
            "node-1",
            attempted_at=NOW - timedelta(minutes=2),
            category=SourceFailureCategory.CONNECTION,
            message="temperature node connection failed",
        )

    evaluate(database, NOW)
    edge = state(database, AlertType.EDGE_UNAVAILABLE)
    assert edge.lifecycle is AlertLifecycleState.HEALTHY
    assert edge.evidence_category == "unknown"


def test_concurrent_evaluations_create_one_active_incident(tmp_path) -> None:
    database = tmp_path / "concurrent-alert.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW - timedelta(minutes=10)))
    evaluate(database, NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: evaluate(database, NOW + timedelta(seconds=30)),
                range(2),
            )
        )

    with SqliteAlertQueryRepository(database) as repository:
        incidents = repository.incidents(
            "node-1",
            status=AlertIncidentStatus.ACTIVE,
            limit=10,
        )
    assert len(incidents) == 1
    assert sum(len(result.transitions) for result in results) == 1


def test_alert_overview_filters_history_and_detects_stale_evaluator(tmp_path) -> None:
    database = tmp_path / "overview.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW - timedelta(minutes=10)))
    evaluate(database, NOW)
    evaluate(database, NOW + timedelta(seconds=30))

    overview = GetOperationalAlerts(
        lambda: SqliteAlertQueryRepository(database),
        evaluator_stale_after_seconds=90,
        clock=lambda: NOW + timedelta(seconds=60),
    ).execute(
        "node-1",
        history_filter=AlertHistoryFilter.ACTIVE,
        limit=5,
    )
    assert overview.status is AlertStatusSummary.ALERTING
    assert overview.active_count == 1
    assert len(overview.incidents) == 1

    stale = GetOperationalAlerts(
        lambda: SqliteAlertQueryRepository(database),
        evaluator_stale_after_seconds=90,
        clock=lambda: NOW + timedelta(seconds=121),
    ).execute("node-1")
    assert stale.status is AlertStatusSummary.UNKNOWN


def test_all_history_never_hides_an_old_active_incident(tmp_path) -> None:
    database = tmp_path / "active-priority.db"
    run_migrations(database)
    with SqliteAlertEvaluationRepository(database) as repository:
        repository.begin_evaluation()
        active = repository.create_incident(
            device_id="node-1",
            alert_type=AlertType.TELEMETRY_STALE,
            suspect_started_at=NOW,
            alerting_at=NOW,
            evidence_category="stale",
            evidence_message="Telemetry has remained stale",
        )
        for offset in range(25):
            incident = repository.create_incident(
                device_id="node-1",
                alert_type=AlertType.EDGE_UNAVAILABLE,
                suspect_started_at=NOW + timedelta(seconds=offset + 1),
                alerting_at=NOW + timedelta(seconds=offset + 1),
                evidence_category="timeout",
                evidence_message="Temperature collection timed out",
            )
            repository.recover_incident(
                incident.id,
                recovered_at=NOW + timedelta(seconds=offset + 2),
                evidence_category="reachable",
                evidence_message="Temperature collection recovered",
            )
        repository.commit()

    overview = GetOperationalAlerts(
        lambda: SqliteAlertQueryRepository(database),
        evaluator_stale_after_seconds=90,
        clock=lambda: NOW + timedelta(minutes=1),
    ).execute("node-1", history_filter=AlertHistoryFilter.ALL, limit=20)

    assert any(incident.id == active.id for incident in overview.incidents)
    assert (
        sum(incident.status is AlertIncidentStatus.RECOVERED for incident in overview.incidents)
        == 20
    )


def test_alert_transaction_rollback_leaves_no_partial_incident(tmp_path) -> None:
    database = tmp_path / "rollback.db"
    run_migrations(database)
    with SqliteAlertEvaluationRepository(database) as repository:
        repository.record_evaluator_started(NOW)
        repository.begin_evaluation()
        repository.create_incident(
            device_id="node-1",
            alert_type=AlertType.TELEMETRY_STALE,
            suspect_started_at=NOW,
            alerting_at=NOW,
            evidence_category="stale",
            evidence_message="Telemetry has remained stale",
        )
        repository.rollback()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM alert_incidents").fetchone()[0] == 0


def test_failed_evaluation_records_sanitized_evaluator_health(tmp_path) -> None:
    database = tmp_path / "failed-evaluator.db"
    run_migrations(database)

    class FailingAlertRepository(SqliteAlertEvaluationRepository):
        def latest_temperature(self, device_id: str):
            raise sqlite3.OperationalError(f"cannot read {device_id} at /private/database.db")

    evaluator = EvaluateOperationalAlerts(
        lambda: FailingAlertRepository(database),
        device_id="node-1",
        policy=POLICY,
        clock=lambda: NOW,
    )

    with pytest.raises(sqlite3.OperationalError):
        evaluator.execute()

    with SqliteAlertQueryRepository(database) as repository:
        runtime = repository.evaluator_runtime()
        assert runtime is not None
        assert runtime.last_outcome is EvaluatorOutcome.FAILURE
        assert runtime.last_error_category == "evaluation_failure"
        assert runtime.last_error_message == "operational alert evaluation failed"
