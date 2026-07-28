"""Environment-based read-only API configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from personal_edge_lab.apps.configuration import (
    ConfigurationError,
    read_bool,
    read_file_path,
    read_http_url,
    read_log_level,
    read_nonblank,
    read_port,
    read_positive_float,
    read_positive_int,
)


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
    alert_evaluator_stale_after_seconds: float = 90.0
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
    email_triage_workspace_enabled: bool = False
    gmail_triage_review_enabled: bool = False

    @property
    def triage_workspace_enabled(self) -> bool:
        return self.email_triage_workspace_enabled or self.gmail_triage_review_enabled

    @classmethod
    def from_env(cls) -> Settings:
        host = read_nonblank("API_HOST", "127.0.0.1")
        port = read_port("API_PORT", "8000")
        stale_after = read_positive_float("API_TELEMETRY_STALE_AFTER_SECONDS", "45")
        collector_stale_after = read_positive_float(
            "API_COLLECTOR_STALE_AFTER_SECONDS",
            "45",
        )
        alert_evaluator_stale_after = read_positive_float(
            "ALERT_EVALUATOR_STALE_AFTER_SECONDS",
            "90",
        )
        docs_enabled = read_bool("API_DOCS_ENABLED", "true")
        public_origin = read_http_url(
            "PUBLIC_ORIGIN",
            "https://rubik-edge-01.local",
        )
        origin = urlparse(public_origin)
        if origin.scheme not in {"http", "https"} or not origin.netloc:
            raise ConfigurationError("PUBLIC_ORIGIN must be an absolute HTTP(S) origin")
        if origin.path or origin.params or origin.query or origin.fragment:
            raise ConfigurationError("PUBLIC_ORIGIN must not contain a path")

        auth_enabled = read_bool("API_AUTH_ENABLED", "false")
        ac_control_enabled = read_bool("API_AC_CONTROL_ENABLED", "false")
        owner_id = read_nonblank("AUTH_OWNER_ID", "owner")
        password_hash_file = read_file_path(
            "AUTH_PASSWORD_HASH_FILE",
            "./secrets/owner-password.hash",
        )
        session_idle_seconds = read_positive_int("AUTH_SESSION_IDLE_SECONDS", "86400")
        session_absolute_seconds = read_positive_int("AUTH_SESSION_ABSOLUTE_SECONDS", "604800")
        login_max_failures = read_positive_int("AUTH_LOGIN_MAX_FAILURES", "5")
        login_window_seconds = read_positive_int("AUTH_LOGIN_WINDOW_SECONDS", "900")
        login_block_seconds = read_positive_int("AUTH_LOGIN_BLOCK_SECONDS", "900")
        command_rate_limit = read_positive_int("API_AC_COMMAND_RATE_LIMIT_PER_MINUTE", "6")
        ac_node_base_url = read_http_url(
            "AC_NODE_BASE_URL",
            "http://ac-controller-01.local",
        )
        ac_command_timeout_seconds = read_positive_float("AC_COMMAND_TIMEOUT_SECONDS", "5")
        if "EMAIL_TRIAGE_WORKSPACE_ENABLED" in os.environ:
            email_triage_workspace_enabled = read_bool(
                "EMAIL_TRIAGE_WORKSPACE_ENABLED",
                "false",
            )
        else:
            email_triage_workspace_enabled = read_bool(
                "GMAIL_TRIAGE_REVIEW_ENABLED",
                "false",
            )

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
        if email_triage_workspace_enabled and not auth_enabled:
            raise ConfigurationError("email triage workspace requires API_AUTH_ENABLED=true")

        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        device_id = read_nonblank("DEVICE_ID", "ac-controller-01")
        level, level_name = read_log_level()

        return cls(
            host=host,
            port=port,
            telemetry_stale_after_seconds=stale_after,
            collector_stale_after_seconds=collector_stale_after,
            alert_evaluator_stale_after_seconds=alert_evaluator_stale_after,
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
            email_triage_workspace_enabled=email_triage_workspace_enabled,
            gmail_triage_review_enabled=email_triage_workspace_enabled,
        )
