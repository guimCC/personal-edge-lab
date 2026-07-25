"""Reusable telemetry read use cases and freshness evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from personal_edge_lab.application.ports.telemetry import (
    CollectorStatusRepository,
    TelemetryRepository,
)
from personal_edge_lab.domain.telemetry import (
    CollectionAttemptOutcome,
    TemperatureBucket,
    TemperatureReading,
)

DEFAULT_HISTORY_LIMIT = 100
MAX_HISTORY_LIMIT = 1000


class TelemetryQueryError(ValueError):
    """Raised when a telemetry query is invalid."""


class TelemetryFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    NO_DATA = "no_data"


class TelemetryWindow(StrEnum):
    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    TWENTY_FOUR_HOURS = "24h"


class CollectorHealthStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    STALE = "stale"
    NO_DATA = "no_data"


class EdgeNodeHealthStatus(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TelemetryHealth:
    status: TelemetryFreshness
    device_id: str
    last_received_at: datetime | None
    age_seconds: float | None
    stale_after_seconds: float


@dataclass(frozen=True, slots=True)
class TelemetrySeries:
    device_id: str
    window: TelemetryWindow
    start_at: datetime
    end_at: datetime
    bucket_seconds: int
    sample_count: int
    items: list[TemperatureBucket]


@dataclass(frozen=True, slots=True)
class CollectorHealth:
    status: CollectorHealthStatus
    device_id: str
    process_started_at: datetime | None
    heartbeat_at: datetime | None
    heartbeat_age_seconds: float | None
    stale_after_seconds: float
    stopped_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int


@dataclass(frozen=True, slots=True)
class EdgeNodeHealth:
    status: EdgeNodeHealthStatus
    device_id: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_category: str | None
    last_failure_message: str | None


@dataclass(frozen=True, slots=True)
class OperationalHealth:
    collector: CollectorHealth
    edge_node: EdgeNodeHealth


WINDOW_CONFIGURATION = {
    TelemetryWindow.ONE_HOUR: (3600, 60),
    TelemetryWindow.SIX_HOURS: (21600, 300),
    TelemetryWindow.TWENTY_FOUR_HOURS: (86400, 900),
}


class GetLatestTemperature:
    def __init__(self, repository: TelemetryRepository) -> None:
        self._repository = repository

    def execute(self, device_id: str) -> TemperatureReading | None:
        return self._repository.latest(_device_id(device_id))


class ListTemperatureHistory:
    def __init__(self, repository: TelemetryRepository) -> None:
        self._repository = repository

    def execute(
        self,
        device_id: str,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> list[TemperatureReading]:
        if not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise TelemetryQueryError(f"limit must be from 1 through {MAX_HISTORY_LIMIT}")
        return self._repository.history(_device_id(device_id), limit=limit)


class GetTemperatureSeries:
    def __init__(
        self,
        repository: TelemetryRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        device_id: str,
        *,
        window: TelemetryWindow = TelemetryWindow.SIX_HOURS,
    ) -> TelemetrySeries:
        selected_device = _device_id(device_id)
        checked_at = _utc_time(self._clock())
        window_seconds, bucket_seconds = WINDOW_CONFIGURATION[window]
        start_at = checked_at - timedelta(seconds=window_seconds)
        stored = self._repository.series(
            selected_device,
            start_at=start_at,
            end_at=checked_at,
            bucket_seconds=bucket_seconds,
        )
        stored_by_start = {bucket.start_at: bucket for bucket in stored}
        items = []
        for offset in range(0, window_seconds, bucket_seconds):
            bucket_start = start_at + timedelta(seconds=offset)
            bucket_end = bucket_start + timedelta(seconds=bucket_seconds)
            items.append(
                stored_by_start.get(
                    bucket_start,
                    TemperatureBucket(
                        start_at=bucket_start,
                        end_at=bucket_end,
                        sample_count=0,
                        minimum_c=None,
                        average_c=None,
                        maximum_c=None,
                    ),
                )
            )
        return TelemetrySeries(
            device_id=selected_device,
            window=window,
            start_at=start_at,
            end_at=checked_at,
            bucket_seconds=bucket_seconds,
            sample_count=sum(bucket.sample_count for bucket in items),
            items=items,
        )


class GetTelemetryHealth:
    def __init__(
        self,
        repository: TelemetryRepository,
        *,
        device_id: str,
        stale_after_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if stale_after_seconds <= 0:
            raise TelemetryQueryError("stale_after_seconds must be greater than zero")
        self._repository = repository
        self._device_id = _device_id(device_id)
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock

    def execute(self) -> TelemetryHealth:
        reading = self._repository.latest(self._device_id)
        if reading is None:
            return TelemetryHealth(
                status=TelemetryFreshness.NO_DATA,
                device_id=self._device_id,
                last_received_at=None,
                age_seconds=None,
                stale_after_seconds=self._stale_after_seconds,
            )

        checked_at = _utc_time(self._clock())
        age_seconds = max(
            0.0,
            (checked_at - reading.received_at).total_seconds(),
        )
        status = (
            TelemetryFreshness.FRESH
            if age_seconds <= self._stale_after_seconds
            else TelemetryFreshness.STALE
        )
        return TelemetryHealth(
            status=status,
            device_id=self._device_id,
            last_received_at=reading.received_at,
            age_seconds=age_seconds,
            stale_after_seconds=self._stale_after_seconds,
        )


class GetOperationalHealth:
    def __init__(
        self,
        repository: CollectorStatusRepository,
        *,
        device_id: str,
        stale_after_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if stale_after_seconds <= 0:
            raise TelemetryQueryError("stale_after_seconds must be greater than zero")
        self._repository = repository
        self._device_id = _device_id(device_id)
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock

    def execute(self) -> OperationalHealth:
        runtime = self._repository.latest(self._device_id)
        if runtime is None:
            return OperationalHealth(
                collector=CollectorHealth(
                    status=CollectorHealthStatus.NO_DATA,
                    device_id=self._device_id,
                    process_started_at=None,
                    heartbeat_at=None,
                    heartbeat_age_seconds=None,
                    stale_after_seconds=self._stale_after_seconds,
                    stopped_at=None,
                    last_attempt_at=None,
                    last_success_at=None,
                    consecutive_failures=0,
                ),
                edge_node=EdgeNodeHealth(
                    status=EdgeNodeHealthStatus.UNKNOWN,
                    device_id=self._device_id,
                    last_attempt_at=None,
                    last_success_at=None,
                    last_failure_at=None,
                    last_failure_category=None,
                    last_failure_message=None,
                ),
            )

        checked_at = _utc_time(self._clock())
        heartbeat_age = max(0.0, (checked_at - runtime.heartbeat_at).total_seconds())
        if runtime.stopped_at is not None:
            collector_status = CollectorHealthStatus.STOPPED
        elif heartbeat_age <= self._stale_after_seconds:
            collector_status = CollectorHealthStatus.RUNNING
        else:
            collector_status = CollectorHealthStatus.STALE

        if collector_status is not CollectorHealthStatus.RUNNING:
            edge_status = EdgeNodeHealthStatus.UNKNOWN
        elif runtime.last_attempt_outcome is CollectionAttemptOutcome.SUCCESS:
            edge_status = EdgeNodeHealthStatus.REACHABLE
        elif runtime.last_attempt_outcome is CollectionAttemptOutcome.FAILURE:
            edge_status = EdgeNodeHealthStatus.UNREACHABLE
        else:
            edge_status = EdgeNodeHealthStatus.UNKNOWN

        return OperationalHealth(
            collector=CollectorHealth(
                status=collector_status,
                device_id=self._device_id,
                process_started_at=runtime.process_started_at,
                heartbeat_at=runtime.heartbeat_at,
                heartbeat_age_seconds=heartbeat_age,
                stale_after_seconds=self._stale_after_seconds,
                stopped_at=runtime.stopped_at,
                last_attempt_at=runtime.last_attempt_at,
                last_success_at=runtime.last_success_at,
                consecutive_failures=runtime.consecutive_failures,
            ),
            edge_node=EdgeNodeHealth(
                status=edge_status,
                device_id=self._device_id,
                last_attempt_at=runtime.last_attempt_at,
                last_success_at=runtime.last_success_at,
                last_failure_at=runtime.last_failure_at,
                last_failure_category=runtime.last_failure_category,
                last_failure_message=runtime.last_failure_message,
            ),
        )


def _utc_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TelemetryQueryError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _device_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TelemetryQueryError("device_id must not be empty")
    return normalized
