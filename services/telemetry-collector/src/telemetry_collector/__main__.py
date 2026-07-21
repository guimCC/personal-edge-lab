"""Telemetry collector process entry point."""

from __future__ import annotations

import logging
import signal
import threading

from telemetry_collector.client import EdgeNodeClient
from telemetry_collector.collector import TelemetryCollector
from telemetry_collector.config import ConfigurationError, Settings
from telemetry_collector.storage import TelemetryStore

LOGGER = logging.getLogger(__name__)


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
        LOGGER.error("Invalid configuration: %s", error)
        return 2

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop_event = threading.Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s; requesting shutdown", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    try:
        with (
            TelemetryStore(settings.database_path) as store,
            EdgeNodeClient(
                url=settings.temperature_url,
                device_id=settings.device_id,
                timeout_seconds=settings.http_timeout_seconds,
            ) as client,
        ):
            TelemetryCollector(
                fetch_temperature=client.fetch_temperature,
                store=store,
                interval_seconds=settings.collection_interval_seconds,
                stop_event=stop_event,
            ).run()
    except OSError as error:
        LOGGER.error("Unable to initialize collector: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
