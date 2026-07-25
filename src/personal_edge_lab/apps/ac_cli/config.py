"""Environment-based AC command configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when AC command configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    node_base_url: str
    command_timeout_seconds: float
    database_path: Path
    log_level: int
    device_id: str

    @classmethod
    def from_env(cls) -> Settings:
        base_url = os.getenv("AC_NODE_BASE_URL", "http://ac-controller-01.local").rstrip("/")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("AC_NODE_BASE_URL must be an absolute HTTP(S) URL")

        timeout = _positive_float("AC_COMMAND_TIMEOUT_SECONDS", "5")
        database_path = Path(os.getenv("DATABASE_PATH", "./data/telemetry.db")).expanduser()
        if database_path.exists() and database_path.is_dir():
            raise ConfigurationError("DATABASE_PATH must name a file, not a directory")

        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = logging.getLevelNamesMapping().get(level_name)
        if level is None:
            raise ConfigurationError(f"LOG_LEVEL is invalid: {level_name}")

        device_id = os.getenv("AC_DEVICE_ID", "ac-controller-01").strip()
        if not device_id:
            raise ConfigurationError("AC_DEVICE_ID must not be empty")

        return cls(base_url, timeout, database_path, level, device_id)


def _positive_float(name: str, default: str) -> float:
    raw_value = os.getenv(name, default)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value
