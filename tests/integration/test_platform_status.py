from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_edge_lab.domain.alerting import AlertPolicy
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.alerting import SqliteAlertRepository
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.alerting import EvaluateOperationalAlerts
from personal_edge_lab.modules.platform_status import GetPlatformHealth, PlatformHealthStatus

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


def platform_health(database, now: datetime = NOW):
    return GetPlatformHealth(
        telemetry_repository_factory=lambda: SqliteTelemetryRepository(database),
        collector_repository_factory=lambda: SqliteCollectorStatusRepository(database),
        alert_repository_factory=lambda: SqliteAlertRepository(database),
        device_id="node-1",
        telemetry_stale_after_seconds=45,
        collector_stale_after_seconds=45,
        evaluator_stale_after_seconds=90,
        clock=lambda: now,
    ).execute()


def test_platform_health_is_reusable_without_http_framework(tmp_path) -> None:
    database = tmp_path / "platform-health.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW))
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(minutes=1))
        repository.record_success("node-1", attempted_at=NOW)
    EvaluateOperationalAlerts(
        lambda: SqliteAlertRepository(database),
        device_id="node-1",
        policy=POLICY,
        clock=lambda: NOW,
    ).execute()

    result = platform_health(database)

    assert result.status is PlatformHealthStatus.HEALTHY
    assert result.checked_at == NOW
    assert result.telemetry.status == "fresh"
    assert result.collector.status == "running"
    assert result.edge_node.status == "reachable"
    assert result.alerts.status == "healthy"


def test_platform_health_degrades_consistently_when_evidence_is_missing(tmp_path) -> None:
    database = tmp_path / "empty-platform-health.db"
    run_migrations(database)

    result = platform_health(database)

    assert result.status is PlatformHealthStatus.DEGRADED
    assert result.telemetry.status == "no_data"
    assert result.collector.status == "no_data"
    assert result.edge_node.status == "unknown"
    assert result.alerts.status == "unknown"
