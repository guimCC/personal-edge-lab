"""Telemetry collector composition root and process entry point."""

from __future__ import annotations

import logging
import signal
import sqlite3
import threading

import httpx

from personal_edge_lab.apps.telemetry_collector.config import (
    ConfigurationError,
    Settings,
)
from personal_edge_lab.apps.telemetry_collector.polling import TelemetryPollingLoop
from personal_edge_lab.infrastructure.esp32.temperature_source import EdgeNodeClient
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.telemetry import CollectTemperature

LOGGER = logging.getLogger(__name__)


def main(
    *,
    transport: httpx.BaseTransport | None = None,
    stop_event: threading.Event | None = None,
) -> int:
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
    shutdown = stop_event or threading.Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s; requesting shutdown", signal.Signals(signum).name)
        shutdown.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    try:
        run_migrations(settings.database_path)
        with (
            SqliteTelemetryRepository(settings.database_path) as repository,
            EdgeNodeClient(
                url=settings.temperature_url,
                device_id=settings.device_id,
                timeout_seconds=settings.http_timeout_seconds,
                transport=transport,
            ) as source,
        ):
            use_case = CollectTemperature(source=source, repository=repository)
            TelemetryPollingLoop(
                collect_once=use_case.execute,
                interval_seconds=settings.collection_interval_seconds,
                stop_event=shutdown,
            ).run()
    except (OSError, sqlite3.Error) as error:
        LOGGER.error("Unable to initialize collector: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
