"""Polling orchestration and failure log suppression."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from telemetry_collector.client import CollectionError
from telemetry_collector.models import TemperatureReading
from telemetry_collector.storage import TelemetryStore

LOGGER = logging.getLogger(__name__)
FAILURE_REMINDER_EVERY = 20


class TelemetryCollector:
    def __init__(
        self,
        *,
        fetch_temperature: Callable[[], TemperatureReading],
        store: TelemetryStore,
        interval_seconds: float,
        stop_event: threading.Event,
    ) -> None:
        self._fetch_temperature = fetch_temperature
        self._store = store
        self._interval_seconds = interval_seconds
        self._stop_event = stop_event
        self._consecutive_failures = 0

    def collect_once(self) -> bool:
        try:
            reading = self._fetch_temperature()
        except CollectionError as error:
            self._record_failure(error)
            return False

        if self._consecutive_failures:
            LOGGER.info("Edge node recovered after %d failed attempts", self._consecutive_failures)
        self._consecutive_failures = 0
        row_id = self._store.insert(reading)
        LOGGER.info(
            "Stored reading id=%d device=%s temperature_c=%.2f age_ms=%d",
            row_id,
            reading.device_id,
            reading.temperature_c,
            reading.age_ms,
        )
        return True

    def run(self) -> None:
        LOGGER.info("Telemetry collector started; interval=%.3fs", self._interval_seconds)
        while not self._stop_event.is_set():
            self.collect_once()
            self._stop_event.wait(self._interval_seconds)
        LOGGER.info("Telemetry collector stopped")

    def _record_failure(self, error: CollectionError) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures == 1:
            LOGGER.error("Temperature collection failed: %s", error)
        elif self._consecutive_failures % FAILURE_REMINDER_EVERY == 0:
            LOGGER.warning(
                "Temperature collection still failing (%d consecutive attempts): %s",
                self._consecutive_failures,
                error,
            )
