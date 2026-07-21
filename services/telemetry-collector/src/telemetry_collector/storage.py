"""SQLite persistence for temperature history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from telemetry_collector.models import TemperatureReading

SCHEMA = """
CREATE TABLE IF NOT EXISTS temperature_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    received_at_utc TEXT NOT NULL,
    estimated_sample_at_utc TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    raw_adc INTEGER NOT NULL,
    age_ms INTEGER NOT NULL,
    sample_interval_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_temperature_device_received
ON temperature_readings (device_id, received_at_utc);
"""


class TelemetryStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def __enter__(self) -> TelemetryStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def insert(self, reading: TemperatureReading) -> int:
        cursor = self._connection.execute(
            """
            INSERT INTO temperature_readings (
                device_id, sensor_type, received_at_utc, estimated_sample_at_utc,
                temperature_c, raw_adc, age_ms, sample_interval_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading.device_id,
                reading.sensor,
                reading.received_at.isoformat(),
                reading.estimated_sample_at.isoformat(),
                reading.temperature_c,
                reading.raw_adc,
                reading.age_ms,
                reading.sample_interval_ms,
            ),
        )
        self._connection.commit()
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("SQLite did not return an inserted row ID")
        return cursor.lastrowid

    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM temperature_readings"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("failed to count temperature readings")
        return int(row["count"])

    def latest(self) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM temperature_readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
