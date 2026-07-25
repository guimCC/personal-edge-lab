from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import SqliteTelemetryRepository


def reading(
    *,
    device_id: str = "node-1",
    received_at: datetime = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
    temperature_c: float = 21.5,
) -> TemperatureReading:
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": temperature_c,
            "raw_adc": 1700,
            "age_ms": 500,
            "sample_interval_ms": 2000,
        },
        device_id=device_id,
        received_at=received_at,
    )


def test_schema_initialization(tmp_path) -> None:
    database = tmp_path / "nested" / "telemetry.db"
    run_migrations(database)
    with sqlite3.connect(database) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "temperature_readings" in names
    assert "idx_temperature_device_received" in names


def test_insert_and_retrieve(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as store:
        row_id = store.insert(reading())
        row = store.latest("node-1")
        assert store.count() == 1
    assert row_id == 1
    assert row is not None
    assert row.device_id == "node-1"
    assert row.temperature_c == 21.5
    assert row.received_at.isoformat() == "2026-07-21T12:00:00+00:00"
    assert row.estimated_sample_at.isoformat() == "2026-07-21T11:59:59.500000+00:00"


def test_history_filters_device_and_returns_newest_first(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as store:
        store.insert(
            reading(
                received_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
                temperature_c=20,
            )
        )
        store.insert(reading(device_id="node-2", temperature_c=30))
        store.insert(
            reading(
                received_at=datetime(2026, 7, 21, 12, 1, tzinfo=UTC),
                temperature_c=22,
            )
        )
        rows = store.history("node-1", limit=2)

    assert [row.temperature_c for row in rows] == [22, 20]
    assert all(isinstance(row, TemperatureReading) for row in rows)
    assert all(row.device_id == "node-1" for row in rows)


def test_history_returns_empty_list_for_unknown_device(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as store:
        assert store.history("unknown", limit=100) == []


def test_separate_connections_support_collection_and_api_reads(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)

    def write_readings() -> None:
        with SqliteTelemetryRepository(database) as store:
            for index in range(25):
                store.insert(reading(temperature_c=20 + index / 10))

    def read_history() -> list[TemperatureReading]:
        observed: list[TemperatureReading] = []
        with SqliteTelemetryRepository(database) as store:
            for _ in range(50):
                observed = store.history("node-1", limit=10)
        return observed

    with ThreadPoolExecutor(max_workers=2) as pool:
        write_future = pool.submit(write_readings)
        read_future = pool.submit(read_history)
        write_future.result()
        observed = read_future.result()

    with SqliteTelemetryRepository(database) as store:
        final = store.history("node-1", limit=100)
    assert len(final) == 25
    assert all(isinstance(item, TemperatureReading) for item in observed)
