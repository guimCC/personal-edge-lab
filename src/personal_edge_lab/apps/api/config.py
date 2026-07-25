"""Environment-based read-only API configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when API configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    telemetry_stale_after_seconds: float
    docs_enabled: bool
    database_path: Path
    device_id: str
    log_level: int
    log_level_name: str
    collector_stale_after_seconds: float = 45.0

    @classmethod
    def from_env(cls) -> Settings:
        host = os.getenv("API_HOST", "127.0.0.1").strip()
        if not host:
            raise ConfigurationError("API_HOST must not be empty")

        port = _port("API_PORT", "8000")
        stale_after = _positive_float("API_TELEMETRY_STALE_AFTER_SECONDS", "45")
        collector_stale_after = _positive_float(
            "API_COLLECTOR_STALE_AFTER_SECONDS",
            "45",
        )
        docs_enabled = _boolean("API_DOCS_ENABLED", "true")

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

        return cls(
            host=host,
            port=port,
            telemetry_stale_after_seconds=stale_after,
            collector_stale_after_seconds=collector_stale_after,
            docs_enabled=docs_enabled,
            database_path=database_path,
            device_id=device_id,
            log_level=level,
            log_level_name=level_name,
        )


def _port(name: str, default: str) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if not 1 <= value <= 65535:
        raise ConfigurationError(f"{name} must be from 1 through 65535")
    return value


def _positive_float(name: str, default: str) -> float:
    raw_value = os.getenv(name, default)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _boolean(name: str, default: str) -> bool:
    raw_value = os.getenv(name, default).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")
