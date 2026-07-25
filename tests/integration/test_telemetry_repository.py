from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import SqliteTelemetryRepository


def reading() -> TemperatureReading:
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": 21.5,
            "raw_adc": 1700,
            "age_ms": 500,
            "sample_interval_ms": 2000,
        },
        device_id="node-1",
        received_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
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
