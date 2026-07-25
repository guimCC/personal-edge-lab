"""Reusable telemetry read use cases and freshness evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from personal_edge_lab.application.ports.telemetry import TelemetryRepository
from personal_edge_lab.domain.telemetry import TemperatureReading

DEFAULT_HISTORY_LIMIT = 100
MAX_HISTORY_LIMIT = 1000


class TelemetryQueryError(ValueError):
    """Raised when a telemetry query is invalid."""


class TelemetryFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    NO_DATA = "no_data"


@dataclass(frozen=True, slots=True)
class TelemetryHealth:
    status: TelemetryFreshness
    device_id: str
    last_received_at: datetime | None
    age_seconds: float | None
    stale_after_seconds: float


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

        checked_at = self._clock()
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise TelemetryQueryError("clock must return a timezone-aware datetime")
        age_seconds = max(
            0.0,
            (checked_at.astimezone(UTC) - reading.received_at).total_seconds(),
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


def _device_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TelemetryQueryError("device_id must not be empty")
    return normalized
