"""Small, shared environment parsing primitives for composition roots."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when an application environment value is invalid."""


def read_nonblank(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise ConfigurationError(f"{name} must not be empty")
    return value


def read_positive_float(name: str, default: str) -> float:
    raw_value = os.getenv(name, default)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if not math.isfinite(value) or value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def read_positive_int(name: str, default: str) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def read_port(name: str, default: str) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if not 1 <= value <= 65535:
        raise ConfigurationError(f"{name} must be from 1 through 65535")
    return value


def read_bool(name: str, default: str) -> bool:
    raw_value = os.getenv(name, default).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def read_log_level(name: str = "LOG_LEVEL", default: str = "INFO") -> tuple[int, str]:
    level_name = os.getenv(name, default).upper()
    level = logging.getLevelNamesMapping().get(level_name)
    if level is None:
        raise ConfigurationError(f"{name} is invalid: {level_name}")
    return level, level_name


def read_file_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default)).expanduser()
    if path.exists() and path.is_dir():
        raise ConfigurationError(f"{name} must name a file, not a directory")
    return path


def read_http_url(name: str, default: str) -> str:
    value = os.getenv(name, default).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{name} must be an absolute HTTP(S) URL")
    return value
