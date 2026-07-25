"""SQLite telemetry repository."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from personal_edge_lab.domain.telemetry import TemperatureBucket, TemperatureReading


class SqliteTelemetryRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = sqlite3.connect(database_path, timeout=timeout_seconds)
        self._connection.row_factory = sqlite3.Row

    def __enter__(self) -> SqliteTelemetryRepository:
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

    def latest(self, device_id: str) -> TemperatureReading | None:
        row = self._connection.execute(
            """
            SELECT device_id, sensor_type, received_at_utc, estimated_sample_at_utc,
                   temperature_c, raw_adc, age_ms, sample_interval_ms
            FROM temperature_readings
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return None if row is None else _reading_from_row(row)

    def history(self, device_id: str, *, limit: int) -> list[TemperatureReading]:
        rows = self._connection.execute(
            """
            SELECT device_id, sensor_type, received_at_utc, estimated_sample_at_utc,
                   temperature_c, raw_adc, age_ms, sample_interval_ms
            FROM temperature_readings
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (device_id, limit),
        )
        return [_reading_from_row(row) for row in rows]

    def series(
        self,
        device_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        bucket_seconds: int,
    ) -> list[TemperatureBucket]:
        rows = self._connection.execute(
            """
            SELECT
                CAST(
                    (unixepoch(received_at_utc) - unixepoch(?)) / ?
                    AS INTEGER
                ) AS bucket_index,
                COUNT(*) AS sample_count,
                MIN(temperature_c) AS minimum_c,
                AVG(temperature_c) AS average_c,
                MAX(temperature_c) AS maximum_c
            FROM temperature_readings
            WHERE device_id = ?
              AND received_at_utc >= ?
              AND received_at_utc < ?
            GROUP BY bucket_index
            ORDER BY bucket_index ASC
            """,
            (
                start_at.isoformat(),
                bucket_seconds,
                device_id,
                start_at.isoformat(),
                end_at.isoformat(),
            ),
        )
        return [
            TemperatureBucket(
                start_at=start_at + timedelta(seconds=int(row["bucket_index"]) * bucket_seconds),
                end_at=start_at
                + timedelta(seconds=(int(row["bucket_index"]) + 1) * bucket_seconds),
                sample_count=int(row["sample_count"]),
                minimum_c=float(row["minimum_c"]),
                average_c=float(row["average_c"]),
                maximum_c=float(row["maximum_c"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM temperature_readings"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("failed to count temperature readings")
        return int(row["count"])


def _reading_from_row(row: sqlite3.Row) -> TemperatureReading:
    return TemperatureReading(
        device_id=str(row["device_id"]),
        sensor=str(row["sensor_type"]),
        received_at=datetime.fromisoformat(row["received_at_utc"]),
        estimated_sample_at=datetime.fromisoformat(row["estimated_sample_at_utc"]),
        temperature_c=float(row["temperature_c"]),
        raw_adc=int(row["raw_adc"]),
        age_ms=int(row["age_ms"]),
        sample_interval_ms=int(row["sample_interval_ms"]),
    )
