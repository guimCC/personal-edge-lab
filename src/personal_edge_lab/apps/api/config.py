"""Environment-based read-only API configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


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
    public_origin: str = "https://rubik-edge-01.local"
    auth_enabled: bool = False
    ac_control_enabled: bool = False
    owner_id: str = "owner"
    password_hash_file: Path = Path("./secrets/owner-password.hash")
    session_idle_seconds: int = 86_400
    session_absolute_seconds: int = 604_800
    login_max_failures: int = 5
    login_window_seconds: int = 900
    login_block_seconds: int = 900
    command_rate_limit_per_minute: int = 6
    ac_node_base_url: str = "http://ac-controller-01.local"
    ac_command_timeout_seconds: float = 5.0

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
        public_origin = os.getenv("PUBLIC_ORIGIN", "https://rubik-edge-01.local").rstrip("/")
        origin = urlparse(public_origin)
        if origin.scheme not in {"http", "https"} or not origin.netloc:
            raise ConfigurationError("PUBLIC_ORIGIN must be an absolute HTTP(S) origin")
        if origin.path or origin.params or origin.query or origin.fragment:
            raise ConfigurationError("PUBLIC_ORIGIN must not contain a path")

        auth_enabled = _boolean("API_AUTH_ENABLED", "false")
        ac_control_enabled = _boolean("API_AC_CONTROL_ENABLED", "false")
        owner_id = os.getenv("AUTH_OWNER_ID", "owner").strip()
        if not owner_id:
            raise ConfigurationError("AUTH_OWNER_ID must not be empty")
        password_hash_file = Path(
            os.getenv(
                "AUTH_PASSWORD_HASH_FILE",
                "./secrets/owner-password.hash",
            )
        ).expanduser()
        session_idle_seconds = _positive_int("AUTH_SESSION_IDLE_SECONDS", "86400")
        session_absolute_seconds = _positive_int("AUTH_SESSION_ABSOLUTE_SECONDS", "604800")
        login_max_failures = _positive_int("AUTH_LOGIN_MAX_FAILURES", "5")
        login_window_seconds = _positive_int("AUTH_LOGIN_WINDOW_SECONDS", "900")
        login_block_seconds = _positive_int("AUTH_LOGIN_BLOCK_SECONDS", "900")
        command_rate_limit = _positive_int("API_AC_COMMAND_RATE_LIMIT_PER_MINUTE", "6")
        ac_node_base_url = os.getenv("AC_NODE_BASE_URL", "http://ac-controller-01.local").rstrip(
            "/"
        )
        node_url = urlparse(ac_node_base_url)
        if node_url.scheme not in {"http", "https"} or not node_url.netloc:
            raise ConfigurationError("AC_NODE_BASE_URL must be an absolute HTTP(S) URL")
        ac_command_timeout_seconds = _positive_float("AC_COMMAND_TIMEOUT_SECONDS", "5")

        if session_idle_seconds > session_absolute_seconds:
            raise ConfigurationError(
                "AUTH_SESSION_IDLE_SECONDS must not exceed AUTH_SESSION_ABSOLUTE_SECONDS"
            )
        if auth_enabled:
            if origin.scheme != "https":
                raise ConfigurationError("authentication requires an HTTPS PUBLIC_ORIGIN")
            if not password_hash_file.is_file():
                raise ConfigurationError(
                    "authentication requires a readable AUTH_PASSWORD_HASH_FILE"
                )
            try:
                password_hash_file.read_text(encoding="utf-8")
            except OSError as error:
                raise ConfigurationError(
                    "authentication requires a readable AUTH_PASSWORD_HASH_FILE"
                ) from error
        if ac_control_enabled:
            if not auth_enabled:
                raise ConfigurationError("AC controls require authentication")
            if docs_enabled:
                raise ConfigurationError("AC controls require API_DOCS_ENABLED=false")

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
            public_origin=public_origin,
            auth_enabled=auth_enabled,
            ac_control_enabled=ac_control_enabled,
            owner_id=owner_id,
            password_hash_file=password_hash_file,
            session_idle_seconds=session_idle_seconds,
            session_absolute_seconds=session_absolute_seconds,
            login_max_failures=login_max_failures,
            login_window_seconds=login_window_seconds,
            login_block_seconds=login_block_seconds,
            command_rate_limit_per_minute=command_rate_limit,
            ac_node_base_url=ac_node_base_url,
            ac_command_timeout_seconds=ac_command_timeout_seconds,
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


def _positive_int(name: str, default: str) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
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
