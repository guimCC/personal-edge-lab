"""Framework-independent composition of platform health."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from personal_edge_lab.application.ports.alerting import AlertQueryRepositoryFactory
from personal_edge_lab.application.ports.telemetry import (
    CollectorStatusRepository,
    TelemetryRepository,
)
from personal_edge_lab.modules.alerting import (
    AlertHistoryFilter,
    AlertOverview,
    AlertStatusSummary,
    GetOperationalAlerts,
)
from personal_edge_lab.modules.telemetry import (
    CollectorHealth,
    CollectorHealthStatus,
    EdgeNodeHealth,
    EdgeNodeHealthStatus,
    GetOperationalHealth,
    GetTelemetryHealth,
    TelemetryFreshness,
    TelemetryHealth,
)


class PlatformHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class PlatformHealth:
    status: PlatformHealthStatus
    checked_at: datetime
    telemetry: TelemetryHealth
    collector: CollectorHealth
    edge_node: EdgeNodeHealth
    alerts: AlertOverview


TelemetryRepositoryFactory = Callable[[], AbstractContextManager[TelemetryRepository]]
CollectorRepositoryFactory = Callable[[], AbstractContextManager[CollectorStatusRepository]]


class GetPlatformHealth:
    def __init__(
        self,
        *,
        telemetry_repository_factory: TelemetryRepositoryFactory,
        collector_repository_factory: CollectorRepositoryFactory,
        alert_repository_factory: AlertQueryRepositoryFactory,
        device_id: str,
        telemetry_stale_after_seconds: float,
        collector_stale_after_seconds: float,
        evaluator_stale_after_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._telemetry_repository_factory = telemetry_repository_factory
        self._collector_repository_factory = collector_repository_factory
        self._alert_repository_factory = alert_repository_factory
        self._device_id = device_id
        self._telemetry_stale_after_seconds = telemetry_stale_after_seconds
        self._collector_stale_after_seconds = collector_stale_after_seconds
        self._evaluator_stale_after_seconds = evaluator_stale_after_seconds
        self._clock = clock

    def execute(self) -> PlatformHealth:
        checked_at = _utc_time(self._clock())
        with self._telemetry_repository_factory() as repository:
            telemetry = GetTelemetryHealth(
                repository,
                device_id=self._device_id,
                stale_after_seconds=self._telemetry_stale_after_seconds,
                clock=lambda: checked_at,
            ).execute()
        with self._collector_repository_factory() as repository:
            operational = GetOperationalHealth(
                repository,
                device_id=self._device_id,
                stale_after_seconds=self._collector_stale_after_seconds,
                clock=lambda: checked_at,
            ).execute()
        alerts = GetOperationalAlerts(
            self._alert_repository_factory,
            evaluator_stale_after_seconds=self._evaluator_stale_after_seconds,
            clock=lambda: checked_at,
        ).execute(
            self._device_id,
            history_filter=AlertHistoryFilter.ACTIVE,
            limit=1,
        )
        healthy = (
            telemetry.status is TelemetryFreshness.FRESH
            and operational.collector.status is CollectorHealthStatus.RUNNING
            and operational.edge_node.status is EdgeNodeHealthStatus.REACHABLE
            and alerts.status
            in {
                AlertStatusSummary.HEALTHY,
                AlertStatusSummary.RECOVERED,
            }
        )
        return PlatformHealth(
            status=(PlatformHealthStatus.HEALTHY if healthy else PlatformHealthStatus.DEGRADED),
            checked_at=checked_at,
            telemetry=telemetry,
            collector=operational.collector,
            edge_node=operational.edge_node,
            alerts=alerts,
        )


def _utc_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)
