from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.modules.telemetry import (
    GetLatestTemperature,
    GetTelemetryHealth,
    ListTemperatureHistory,
    TelemetryFreshness,
    TelemetryQueryError,
)

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)


def reading(*, seconds_old: float = 0, device_id: str = "node-1") -> TemperatureReading:
    received_at = NOW - timedelta(seconds=seconds_old)
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": 24.5,
            "raw_adc": 1700,
            "age_ms": 500,
            "sample_interval_ms": 2000,
        },
        device_id=device_id,
        received_at=received_at,
    )


class Repository:
    def __init__(self, readings: list[TemperatureReading]) -> None:
        self.readings = readings
        self.latest_device_id: str | None = None
        self.history_request: tuple[str, int] | None = None

    def insert(self, value: TemperatureReading) -> int:
        self.readings.append(value)
        return len(self.readings)

    def latest(self, device_id: str) -> TemperatureReading | None:
        self.latest_device_id = device_id
        return next((item for item in self.readings if item.device_id == device_id), None)

    def history(self, device_id: str, *, limit: int) -> list[TemperatureReading]:
        self.history_request = (device_id, limit)
        return [item for item in self.readings if item.device_id == device_id][:limit]


def test_latest_normalizes_device_id_and_returns_domain_reading() -> None:
    value = reading()
    repository = Repository([value])
    assert GetLatestTemperature(repository).execute(" node-1 ") is value
    assert repository.latest_device_id == "node-1"


def test_history_uses_bounded_limit_and_device() -> None:
    repository = Repository([reading()])
    values = ListTemperatureHistory(repository).execute("node-1", limit=25)
    assert values == repository.readings
    assert repository.history_request == ("node-1", 25)


@pytest.mark.parametrize("limit", [0, 1001])
def test_history_rejects_out_of_range_limits(limit: int) -> None:
    with pytest.raises(TelemetryQueryError, match="1 through 1000"):
        ListTemperatureHistory(Repository([])).execute("node-1", limit=limit)


@pytest.mark.parametrize("device_id", ["", "   "])
def test_queries_reject_blank_device_id(device_id: str) -> None:
    with pytest.raises(TelemetryQueryError, match="must not be empty"):
        GetLatestTemperature(Repository([])).execute(device_id)


@pytest.mark.parametrize(
    ("seconds_old", "expected"),
    [
        (45, TelemetryFreshness.FRESH),
        (45.001, TelemetryFreshness.STALE),
    ],
)
def test_health_freshness_boundary(
    seconds_old: float,
    expected: TelemetryFreshness,
) -> None:
    health = GetTelemetryHealth(
        Repository([reading(seconds_old=seconds_old)]),
        device_id="node-1",
        stale_after_seconds=45,
        clock=lambda: NOW,
    ).execute()
    assert health.status is expected
    assert health.age_seconds == seconds_old
    assert health.last_received_at == NOW - timedelta(seconds=seconds_old)


def test_health_reports_no_data() -> None:
    health = GetTelemetryHealth(
        Repository([]),
        device_id="node-1",
        stale_after_seconds=45,
        clock=lambda: NOW,
    ).execute()
    assert health.status is TelemetryFreshness.NO_DATA
    assert health.age_seconds is None
    assert health.last_received_at is None


def test_health_requires_timezone_aware_clock() -> None:
    with pytest.raises(TelemetryQueryError, match="timezone-aware"):
        GetTelemetryHealth(
            Repository([reading()]),
            device_id="node-1",
            stale_after_seconds=45,
            clock=lambda: datetime(2026, 7, 25, 14, 0),
        ).execute()
