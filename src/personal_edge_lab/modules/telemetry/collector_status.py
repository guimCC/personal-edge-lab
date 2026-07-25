"""Collector runtime status recording use case."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from personal_edge_lab.application.ports.telemetry import (
    CollectorStatusRepository,
    TemperatureSourceError,
)


class CollectorStatusMonitor:
    def __init__(
        self,
        repository: CollectorStatusRepository,
        *,
        device_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._device_id = device_id
        self._clock = clock

    def start(self) -> None:
        self._repository.start(self._device_id, started_at=self._now())

    def success(self) -> None:
        self._repository.record_success(self._device_id, attempted_at=self._now())

    def failure(self, error: TemperatureSourceError) -> None:
        self._repository.record_failure(
            self._device_id,
            attempted_at=self._now(),
            category=error.category,
            message=str(error),
        )

    def stop(self) -> None:
        self._repository.stop(self._device_id, stopped_at=self._now())

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collector status clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
