from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from telemetry_collector.client import CollectionError
from telemetry_collector.collector import TelemetryCollector
from telemetry_collector.models import TemperatureReading
from telemetry_collector.storage import TelemetryStore


def valid_reading() -> TemperatureReading:
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": 20.0,
            "raw_adc": 1500,
            "age_ms": 420,
            "sample_interval_ms": 2000,
        },
        device_id="node-1",
        received_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
    )


def collector(fetch, store: TelemetryStore) -> TelemetryCollector:
    return TelemetryCollector(
        fetch_temperature=fetch,
        store=store,
        interval_seconds=15,
        stop_event=threading.Event(),
    )


def test_successful_collection_inserts_reading(tmp_path) -> None:
    with TelemetryStore(tmp_path / "telemetry.db") as store:
        assert collector(valid_reading, store).collect_once()
        assert store.count() == 1


def test_failed_request_does_not_insert_fake_reading(tmp_path) -> None:
    def fail() -> TemperatureReading:
        raise CollectionError("node unavailable")

    with TelemetryStore(tmp_path / "telemetry.db") as store:
        assert not collector(fail, store).collect_once()
        assert store.count() == 0


def test_age_derives_estimated_sample_timestamp() -> None:
    value = valid_reading()
    assert value.estimated_sample_at == value.received_at - timedelta(milliseconds=420)
    assert value.estimated_sample_at.tzinfo is UTC
