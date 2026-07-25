from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from personal_edge_lab.application.ports.telemetry import TemperatureSourceError
from personal_edge_lab.apps.telemetry_collector.polling import TelemetryPollingLoop
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import SqliteTelemetryRepository
from personal_edge_lab.modules.telemetry import CollectionReceipt, CollectTemperature


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


class FunctionSource:
    def __init__(self, fetch):
        self.fetch_temperature = fetch


def collector(fetch, store: SqliteTelemetryRepository) -> TelemetryPollingLoop:
    use_case = CollectTemperature(source=FunctionSource(fetch), repository=store)
    return TelemetryPollingLoop(
        collect_once=use_case.execute,
        interval_seconds=15,
        stop_event=threading.Event(),
    )


def test_successful_collection_inserts_reading(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as store:
        assert collector(valid_reading, store).collect_once()
        assert store.count() == 1


def test_failed_request_does_not_insert_fake_reading(tmp_path) -> None:
    def fail() -> TemperatureReading:
        raise TemperatureSourceError("node unavailable")

    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as store:
        assert not collector(fail, store).collect_once()
        assert store.count() == 0


def test_age_derives_estimated_sample_timestamp() -> None:
    value = valid_reading()
    assert value.estimated_sample_at == value.received_at - timedelta(milliseconds=420)
    assert value.estimated_sample_at.tzinfo is UTC


def test_polling_reports_failure_reminders_and_recovery(caplog) -> None:
    attempts = 0

    def collect() -> CollectionReceipt:
        nonlocal attempts
        attempts += 1
        if attempts <= 20:
            raise TemperatureSourceError("node unavailable")
        return CollectionReceipt(7, valid_reading())

    polling = TelemetryPollingLoop(
        collect_once=collect,
        interval_seconds=15,
        stop_event=threading.Event(),
    )
    with caplog.at_level(logging.INFO):
        for _ in range(21):
            polling.collect_once()

    messages = [record.getMessage() for record in caplog.records]
    assert sum("Temperature collection failed" in message for message in messages) == 1
    assert any("20 consecutive attempts" in message for message in messages)
    assert any("recovered after 20 failed attempts" in message for message in messages)


def test_polling_stops_without_collecting_when_shutdown_was_requested(caplog) -> None:
    stop_event = threading.Event()
    stop_event.set()
    calls = 0

    def collect() -> CollectionReceipt:
        nonlocal calls
        calls += 1
        return CollectionReceipt(1, valid_reading())

    with caplog.at_level(logging.INFO):
        TelemetryPollingLoop(
            collect_once=collect,
            interval_seconds=15,
            stop_event=stop_event,
        ).run()

    assert calls == 0
    assert "Telemetry collector stopped" in caplog.messages
