"""Environment configuration for the Casadaqui owner operations bot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_edge_lab.apps.ai_cli.config import LangfuseSettings
from personal_edge_lab.apps.configuration import (
    ConfigurationError as ConfigurationError,
)
from personal_edge_lab.apps.configuration import (
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
    token_file: Path
    owner_user_id: int
    database_path: Path
    ac_device_id: str
    telemetry_device_id: str
    node_base_url: str
    command_timeout_seconds: float
    command_rate_limit_per_minute: int
    poll_timeout_seconds: int
    api_port: int
    telemetry_stale_after_seconds: float
    collector_stale_after_seconds: float
    alert_evaluator_stale_after_seconds: float
    notification_delivery_enabled: bool
    notification_batch_size: int
    notification_lease_seconds: float
    notification_max_age_seconds: float
    notification_runtime_stale_after_seconds: float
    owner_timezone: ZoneInfo
    log_level: int
    email_triage_feedback_enabled: bool
    langfuse: LangfuseSettings | None

    @classmethod
    def from_env(cls) -> Settings:
        if not read_bool("TELEGRAM_BOT_ENABLED", "false"):
            raise ConfigurationError("TELEGRAM_BOT_ENABLED must be true")
        token_file = read_file_path(
            "TELEGRAM_BOT_TOKEN_FILE",
            "./secrets/telegram-bot.token",
        )
        if not token_file.is_file():
            raise ConfigurationError("TELEGRAM_BOT_TOKEN_FILE must be a readable file")
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN_FILE must be readable") from error
        if not token or any(character.isspace() for character in token):
            raise ConfigurationError("TELEGRAM_BOT_TOKEN_FILE contains an invalid token")

        owner_user_id = read_positive_int("TELEGRAM_OWNER_USER_ID", "0")
        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        ac_device_id = read_nonblank("AC_DEVICE_ID", "ac-controller-01")
        telemetry_device_id = read_nonblank("DEVICE_ID", "ac-controller-01")
        node_base_url = read_http_url(
            "AC_NODE_BASE_URL",
            "http://ac-controller-01.local",
        )
        command_timeout = read_positive_float("AC_COMMAND_TIMEOUT_SECONDS", "5")
        rate_limit = read_positive_int("TELEGRAM_AC_COMMAND_RATE_LIMIT_PER_MINUTE", "6")
        poll_timeout = read_positive_int("TELEGRAM_POLL_TIMEOUT_SECONDS", "25")
        api_port = read_port("API_PORT", "8000")
        telemetry_stale_after = read_positive_float(
            "API_TELEMETRY_STALE_AFTER_SECONDS",
            "45",
        )
        collector_stale_after = read_positive_float(
            "API_COLLECTOR_STALE_AFTER_SECONDS",
            "45",
        )
        alert_evaluator_stale_after = read_positive_float(
            "ALERT_EVALUATOR_STALE_AFTER_SECONDS",
            "90",
        )
        notification_delivery_enabled = read_bool(
            "TELEGRAM_NOTIFICATION_DELIVERY_ENABLED",
            "false",
        )
        notification_batch_size = read_positive_int(
            "TELEGRAM_NOTIFICATION_BATCH_SIZE",
            "20",
        )
        notification_lease_seconds = read_positive_float(
            "TELEGRAM_NOTIFICATION_LEASE_SECONDS",
            "60",
        )
        notification_max_age_seconds = read_positive_float(
            "TELEGRAM_NOTIFICATION_MAX_AGE_SECONDS",
            "86400",
        )
        notification_runtime_stale_after_seconds = read_positive_float(
            "TELEGRAM_NOTIFICATION_RUNTIME_STALE_AFTER_SECONDS",
            "90",
        )
        email_triage_feedback_enabled = read_bool(
            "EMAIL_TRIAGE_FEEDBACK_ENABLED",
            "false",
        )
        langfuse = LangfuseSettings.from_env() if email_triage_feedback_enabled else None
        timezone_name = read_nonblank("OWNER_TIMEZONE", "Europe/Madrid")
        try:
            owner_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ConfigurationError("OWNER_TIMEZONE is not a known timezone") from error
        if poll_timeout > 50:
            raise ConfigurationError("TELEGRAM_POLL_TIMEOUT_SECONDS must not exceed 50")
        if notification_batch_size > 100:
            raise ConfigurationError("TELEGRAM_NOTIFICATION_BATCH_SIZE must not exceed 100")
        if notification_runtime_stale_after_seconds <= poll_timeout + 5:
            raise ConfigurationError(
                "TELEGRAM_NOTIFICATION_RUNTIME_STALE_AFTER_SECONDS must exceed the polling cycle"
            )
        log_level, _level_name = read_log_level()
        return cls(
            token_file=token_file,
            owner_user_id=owner_user_id,
            database_path=database_path,
            ac_device_id=ac_device_id,
            telemetry_device_id=telemetry_device_id,
            node_base_url=node_base_url,
            command_timeout_seconds=command_timeout,
            command_rate_limit_per_minute=rate_limit,
            poll_timeout_seconds=poll_timeout,
            api_port=api_port,
            telemetry_stale_after_seconds=telemetry_stale_after,
            collector_stale_after_seconds=collector_stale_after,
            alert_evaluator_stale_after_seconds=alert_evaluator_stale_after,
            notification_delivery_enabled=notification_delivery_enabled,
            notification_batch_size=notification_batch_size,
            notification_lease_seconds=notification_lease_seconds,
            notification_max_age_seconds=notification_max_age_seconds,
            notification_runtime_stale_after_seconds=(notification_runtime_stale_after_seconds),
            owner_timezone=owner_timezone,
            log_level=log_level,
            email_triage_feedback_enabled=email_triage_feedback_enabled,
            langfuse=langfuse,
        )

    def read_token(self) -> str:
        return self.token_file.read_text(encoding="utf-8").strip()
