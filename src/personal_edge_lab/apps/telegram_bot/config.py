"""Environment configuration for the Telegram AC control bot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personal_edge_lab.apps.configuration import (
    ConfigurationError as ConfigurationError,
)
from personal_edge_lab.apps.configuration import (
    read_bool,
    read_file_path,
    read_http_url,
    read_log_level,
    read_nonblank,
    read_positive_float,
    read_positive_int,
)


@dataclass(frozen=True, slots=True)
class Settings:
    token_file: Path
    owner_user_id: int
    database_path: Path
    device_id: str
    node_base_url: str
    command_timeout_seconds: float
    command_rate_limit_per_minute: int
    poll_timeout_seconds: int
    log_level: int

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
        device_id = read_nonblank("AC_DEVICE_ID", "ac-controller-01")
        node_base_url = read_http_url(
            "AC_NODE_BASE_URL",
            "http://ac-controller-01.local",
        )
        command_timeout = read_positive_float("AC_COMMAND_TIMEOUT_SECONDS", "5")
        rate_limit = read_positive_int("TELEGRAM_AC_COMMAND_RATE_LIMIT_PER_MINUTE", "6")
        poll_timeout = read_positive_int("TELEGRAM_POLL_TIMEOUT_SECONDS", "25")
        if poll_timeout > 50:
            raise ConfigurationError("TELEGRAM_POLL_TIMEOUT_SECONDS must not exceed 50")
        log_level, _level_name = read_log_level()
        return cls(
            token_file=token_file,
            owner_user_id=owner_user_id,
            database_path=database_path,
            device_id=device_id,
            node_base_url=node_base_url,
            command_timeout_seconds=command_timeout,
            command_rate_limit_per_minute=rate_limit,
            poll_timeout_seconds=poll_timeout,
            log_level=log_level,
        )

    def read_token(self) -> str:
        return self.token_file.read_text(encoding="utf-8").strip()
