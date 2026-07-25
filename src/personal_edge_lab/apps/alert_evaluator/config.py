"""Environment configuration for the operational alert evaluator."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from personal_edge_lab.domain.alerting import AlertPolicy


class ConfigurationError(ValueError):
    """Raised when alert evaluator configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    device_id: str
    log_level: int
    log_level_name: str
    evaluation_interval_seconds: float
    evaluator_stale_after_seconds: float
    policy: AlertPolicy

    @classmethod
    def from_env(cls) -> Settings:
        database_path = Path(os.getenv("DATABASE_PATH", "./data/telemetry.db")).expanduser()
        if database_path.exists() and database_path.is_dir():
            raise ConfigurationError("DATABASE_PATH must name a file, not a directory")

        device_id = os.getenv("DEVICE_ID", "ac-controller-01").strip()
        if not device_id:
            raise ConfigurationError("DEVICE_ID must not be empty")

        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = logging.getLevelNamesMapping().get(level_name)
        if level is None:
            raise ConfigurationError(f"LOG_LEVEL is invalid: {level_name}")

        evaluation_interval = _positive_float("ALERT_EVALUATION_INTERVAL_SECONDS", "30")
        evaluator_stale_after = _positive_float(
            "ALERT_EVALUATOR_STALE_AFTER_SECONDS",
            "90",
        )
        if evaluator_stale_after <= evaluation_interval:
            raise ConfigurationError(
                "ALERT_EVALUATOR_STALE_AFTER_SECONDS must exceed ALERT_EVALUATION_INTERVAL_SECONDS"
            )
        try:
            policy = AlertPolicy(
                telemetry_suspect_after_seconds=_positive_float(
                    "ALERT_TELEMETRY_SUSPECT_AFTER_SECONDS",
                    "45",
                ),
                telemetry_alert_after_seconds=_positive_float(
                    "ALERT_TELEMETRY_ALERT_AFTER_SECONDS",
                    "180",
                ),
                edge_min_consecutive_failures=_positive_int(
                    "ALERT_EDGE_MIN_CONSECUTIVE_FAILURES",
                    "4",
                ),
                edge_alert_after_seconds=_positive_float(
                    "ALERT_EDGE_ALERT_AFTER_SECONDS",
                    "45",
                ),
                recovery_display_seconds=_positive_float(
                    "ALERT_RECOVERY_DISPLAY_SECONDS",
                    "300",
                ),
            )
        except ValueError as error:
            raise ConfigurationError(str(error)) from error

        return cls(
            database_path=database_path,
            device_id=device_id,
            log_level=level,
            log_level_name=level_name,
            evaluation_interval_seconds=evaluation_interval,
            evaluator_stale_after_seconds=evaluator_stale_after,
            policy=policy,
        )


def _positive_float(name: str, default: str) -> float:
    raw_value = os.getenv(name, default)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _positive_int(name: str, default: str) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value
