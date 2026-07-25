"""Telemetry application ports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from personal_edge_lab.domain.telemetry import (
    CollectorRuntimeStatus,
    TemperatureBucket,
    TemperatureReading,
)


class SourceFailureCategory(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    HTTP_STATUS = "http_status"
    INVALID_JSON = "invalid_json"
    INVALID_PAYLOAD = "invalid_payload"


class TemperatureSourceError(RuntimeError):
    """Raised when a source cannot provide a valid temperature reading."""

    def __init__(
        self,
        message: str,
        *,
        category: SourceFailureCategory = SourceFailureCategory.CONNECTION,
    ) -> None:
        super().__init__(message)
        self.category = category


class TemperatureSource(Protocol):
    def fetch_temperature(self) -> TemperatureReading: ...


class TelemetryRepository(Protocol):
    def insert(self, reading: TemperatureReading) -> int: ...

    def latest(self, device_id: str) -> TemperatureReading | None: ...

    def history(self, device_id: str, *, limit: int) -> list[TemperatureReading]: ...

    def series(
        self,
        device_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        bucket_seconds: int,
    ) -> list[TemperatureBucket]: ...


class CollectorStatusRepository(Protocol):
    def start(self, device_id: str, *, started_at: datetime) -> None: ...

    def record_success(self, device_id: str, *, attempted_at: datetime) -> None: ...

    def record_failure(
        self,
        device_id: str,
        *,
        attempted_at: datetime,
        category: SourceFailureCategory,
        message: str,
    ) -> None: ...

    def stop(self, device_id: str, *, stopped_at: datetime) -> None: ...

    def latest(self, device_id: str) -> CollectorRuntimeStatus | None: ...
