"""Operational alert evaluator composition root."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from personal_edge_lab.application.ports.alerting import AlertEvaluationRepositoryFactory
from personal_edge_lab.apps.alert_evaluator.config import ConfigurationError, Settings
from personal_edge_lab.apps.logging_config import configure_logging
from personal_edge_lab.infrastructure.persistence.sqlite.alert_evaluation import (
    SqliteAlertEvaluationRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.alerting import EvaluateOperationalAlerts

LOGGER = logging.getLogger(__name__)


def main(
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    repository_factory: AlertEvaluationRepositoryFactory | None = None,
) -> int:
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
        LOGGER.error("Invalid configuration: %s", error)
        return 2

    configure_logging(settings.log_level)
    factory = repository_factory or (
        lambda: SqliteAlertEvaluationRepository(settings.database_path)
    )
    try:
        run_migrations(settings.database_path)
        result = EvaluateOperationalAlerts(
            factory,
            device_id=settings.device_id,
            policy=settings.policy,
            clock=clock,
        ).execute()
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        LOGGER.error("Operational alert evaluation failed: %s", type(error).__name__)
        return 1
    completion_logger = LOGGER.info if result.transitions else LOGGER.debug
    completion_logger(
        "Operational alert evaluation completed device=%s transitions=%d",
        result.device_id,
        len(result.transitions),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
