"""Environment configuration for the operational alert evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personal_edge_lab.apps.configuration import (
    ConfigurationError,
    read_file_path,
    read_log_level,
    read_nonblank,
    read_positive_float,
    read_positive_int,
)
from personal_edge_lab.domain.alerting import AlertPolicy


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
        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        device_id = read_nonblank("DEVICE_ID", "ac-controller-01")
        level, level_name = read_log_level()
        evaluation_interval = read_positive_float("ALERT_EVALUATION_INTERVAL_SECONDS", "30")
        evaluator_stale_after = read_positive_float(
            "ALERT_EVALUATOR_STALE_AFTER_SECONDS",
            "90",
        )
        if evaluator_stale_after <= evaluation_interval:
            raise ConfigurationError(
                "ALERT_EVALUATOR_STALE_AFTER_SECONDS must exceed ALERT_EVALUATION_INTERVAL_SECONDS"
            )
        try:
            policy = AlertPolicy(
                telemetry_suspect_after_seconds=read_positive_float(
                    "ALERT_TELEMETRY_SUSPECT_AFTER_SECONDS",
                    "45",
                ),
                telemetry_alert_after_seconds=read_positive_float(
                    "ALERT_TELEMETRY_ALERT_AFTER_SECONDS",
                    "180",
                ),
                edge_min_consecutive_failures=read_positive_int(
                    "ALERT_EDGE_MIN_CONSECUTIVE_FAILURES",
                    "4",
                ),
                edge_alert_after_seconds=read_positive_float(
                    "ALERT_EDGE_ALERT_AFTER_SECONDS",
                    "45",
                ),
                recovery_display_seconds=read_positive_float(
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
