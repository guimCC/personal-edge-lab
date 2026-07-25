"""Telemetry application ports."""

from __future__ import annotations

from typing import Protocol

from personal_edge_lab.domain.telemetry import TemperatureReading


class TemperatureSourceError(RuntimeError):
    """Raised when a source cannot provide a valid temperature reading."""


class TemperatureSource(Protocol):
    def fetch_temperature(self) -> TemperatureReading: ...


class TelemetryRepository(Protocol):
    def insert(self, reading: TemperatureReading) -> int: ...

    def latest(self, device_id: str) -> TemperatureReading | None: ...

    def history(self, device_id: str, *, limit: int) -> list[TemperatureReading]: ...
