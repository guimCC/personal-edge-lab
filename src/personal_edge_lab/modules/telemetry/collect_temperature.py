"""Collect and persist exactly one temperature reading."""

from __future__ import annotations

from dataclasses import dataclass

from personal_edge_lab.application.ports.telemetry import (
    TelemetryRepository,
    TemperatureSource,
)
from personal_edge_lab.domain.telemetry import TemperatureReading


@dataclass(frozen=True, slots=True)
class CollectionReceipt:
    row_id: int
    reading: TemperatureReading


class CollectTemperature:
    def __init__(
        self,
        *,
        source: TemperatureSource,
        repository: TelemetryRepository,
    ) -> None:
        self._source = source
        self._repository = repository

    def execute(self) -> CollectionReceipt:
        reading = self._source.fetch_temperature()
        return CollectionReceipt(self._repository.insert(reading), reading)
