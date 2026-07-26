from __future__ import annotations

import logging

import pytest

from personal_edge_lab.apps.ac_cli.config import (
    ConfigurationError as AcConfigurationError,
)
from personal_edge_lab.apps.ac_cli.config import Settings as AcSettings
from personal_edge_lab.apps.alert_evaluator.config import (
    ConfigurationError as AlertConfigurationError,
)
from personal_edge_lab.apps.alert_evaluator.config import Settings as AlertSettings
from personal_edge_lab.apps.api.config import (
    ConfigurationError as ApiConfigurationError,
)
from personal_edge_lab.apps.api.config import Settings as ApiSettings
from personal_edge_lab.apps.telegram_bot.config import (
    ConfigurationError as TelegramConfigurationError,
)
from personal_edge_lab.apps.telegram_bot.config import Settings as TelegramSettings
from personal_edge_lab.apps.telemetry_collector.config import (
    ConfigurationError as TelemetryConfigurationError,
)
from personal_edge_lab.apps.telemetry_collector.config import Settings as TelemetrySettings

TELEMETRY_VARIABLES = (
    "EDGE_NODE_BASE_URL",
    "TEMPERATURE_ENDPOINT",
    "COLLECTION_INTERVAL_SECONDS",
    "HTTP_TIMEOUT_SECONDS",
    "DATABASE_PATH",
    "LOG_LEVEL",
    "DEVICE_ID",
)
AC_VARIABLES = (
    "AC_NODE_BASE_URL",
    "AC_COMMAND_TIMEOUT_SECONDS",
    "DATABASE_PATH",
    "LOG_LEVEL",
    "AC_DEVICE_ID",
)
API_VARIABLES = (
    "API_HOST",
    "API_PORT",
    "API_TELEMETRY_STALE_AFTER_SECONDS",
    "API_COLLECTOR_STALE_AFTER_SECONDS",
    "ALERT_EVALUATOR_STALE_AFTER_SECONDS",
    "API_DOCS_ENABLED",
    "PUBLIC_ORIGIN",
    "API_AUTH_ENABLED",
    "API_AC_CONTROL_ENABLED",
    "AUTH_OWNER_ID",
    "AUTH_PASSWORD_HASH_FILE",
    "AUTH_SESSION_IDLE_SECONDS",
    "AUTH_SESSION_ABSOLUTE_SECONDS",
    "AUTH_LOGIN_MAX_FAILURES",
    "AUTH_LOGIN_WINDOW_SECONDS",
    "AUTH_LOGIN_BLOCK_SECONDS",
    "API_AC_COMMAND_RATE_LIMIT_PER_MINUTE",
    "AC_NODE_BASE_URL",
    "AC_COMMAND_TIMEOUT_SECONDS",
    "DATABASE_PATH",
    "DEVICE_ID",
    "LOG_LEVEL",
)
ALERT_VARIABLES = (
    "DATABASE_PATH",
    "DEVICE_ID",
    "LOG_LEVEL",
    "ALERT_EVALUATION_INTERVAL_SECONDS",
    "ALERT_TELEMETRY_SUSPECT_AFTER_SECONDS",
    "ALERT_TELEMETRY_ALERT_AFTER_SECONDS",
    "ALERT_EDGE_MIN_CONSECUTIVE_FAILURES",
    "ALERT_EDGE_ALERT_AFTER_SECONDS",
    "ALERT_RECOVERY_DISPLAY_SECONDS",
    "ALERT_EVALUATOR_STALE_AFTER_SECONDS",
)
TELEGRAM_VARIABLES = (
    "TELEGRAM_BOT_ENABLED",
    "TELEGRAM_BOT_TOKEN_FILE",
    "TELEGRAM_OWNER_USER_ID",
    "TELEGRAM_AC_COMMAND_RATE_LIMIT_PER_MINUTE",
    "TELEGRAM_POLL_TIMEOUT_SECONDS",
    "DATABASE_PATH",
    "AC_DEVICE_ID",
    "AC_NODE_BASE_URL",
    "AC_COMMAND_TIMEOUT_SECONDS",
    "LOG_LEVEL",
)


def clear(monkeypatch, names: tuple[str, ...]) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_telemetry_environment_defaults_are_preserved(monkeypatch) -> None:
    clear(monkeypatch, TELEMETRY_VARIABLES)
    settings = TelemetrySettings.from_env()
    assert settings.temperature_url == "http://ac-controller-01.local/temperature"
    assert settings.collection_interval_seconds == 15
    assert settings.http_timeout_seconds == 5
    assert str(settings.database_path) == "data/telemetry.db"
    assert settings.log_level == logging.INFO
    assert settings.device_id == "ac-controller-01"


def test_telemetry_environment_overrides_are_preserved(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EDGE_NODE_BASE_URL", "https://node.example/")
    monkeypatch.setenv("TEMPERATURE_ENDPOINT", "/cached-temperature")
    monkeypatch.setenv("COLLECTION_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DEVICE_ID", "sensor-7")
    settings = TelemetrySettings.from_env()
    assert settings.temperature_url == "https://node.example/cached-temperature"
    assert settings.collection_interval_seconds == 2.5
    assert settings.http_timeout_seconds == 1.25
    assert settings.database_path == tmp_path / "edge.db"
    assert settings.log_level == logging.DEBUG
    assert settings.device_id == "sensor-7"


def test_ac_environment_defaults_are_preserved(monkeypatch) -> None:
    clear(monkeypatch, AC_VARIABLES)
    settings = AcSettings.from_env()
    assert settings.node_base_url == "http://ac-controller-01.local"
    assert settings.command_timeout_seconds == 5
    assert str(settings.database_path) == "data/telemetry.db"
    assert settings.log_level == logging.INFO
    assert settings.device_id == "ac-controller-01"


def test_ac_environment_overrides_are_preserved(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AC_NODE_BASE_URL", "https://node.example/")
    monkeypatch.setenv("AC_COMMAND_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("AC_DEVICE_ID", "ac-7")
    settings = AcSettings.from_env()
    assert settings.node_base_url == "https://node.example"
    assert settings.command_timeout_seconds == 1.5
    assert settings.database_path == tmp_path / "edge.db"
    assert settings.log_level == logging.WARNING
    assert settings.device_id == "ac-7"


def test_api_environment_defaults(monkeypatch) -> None:
    clear(monkeypatch, API_VARIABLES)
    settings = ApiSettings.from_env()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.telemetry_stale_after_seconds == 45
    assert settings.collector_stale_after_seconds == 45
    assert settings.alert_evaluator_stale_after_seconds == 90
    assert settings.docs_enabled is True
    assert settings.auth_enabled is False
    assert settings.ac_control_enabled is False
    assert settings.public_origin == "https://rubik-edge-01.local"
    assert str(settings.database_path) == "data/telemetry.db"
    assert settings.device_id == "ac-controller-01"
    assert settings.log_level == logging.INFO
    assert settings.log_level_name == "INFO"


def test_api_environment_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8080")
    monkeypatch.setenv("API_TELEMETRY_STALE_AFTER_SECONDS", "60.5")
    monkeypatch.setenv("API_COLLECTOR_STALE_AFTER_SECONDS", "75")
    monkeypatch.setenv("API_DOCS_ENABLED", "off")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("DEVICE_ID", "sensor-7")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = ApiSettings.from_env()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.telemetry_stale_after_seconds == 60.5
    assert settings.collector_stale_after_seconds == 75
    assert settings.docs_enabled is False
    assert settings.database_path == tmp_path / "edge.db"
    assert settings.device_id == "sensor-7"
    assert settings.log_level == logging.DEBUG
    assert settings.log_level_name == "DEBUG"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("EDGE_NODE_BASE_URL", "node.local", "absolute HTTP"),
        ("TEMPERATURE_ENDPOINT", "temperature", "start with"),
        ("COLLECTION_INTERVAL_SECONDS", "0", "greater than zero"),
        ("HTTP_TIMEOUT_SECONDS", "slow", "must be a number"),
        ("DEVICE_ID", " ", "must not be empty"),
        ("LOG_LEVEL", "LOUD", "invalid"),
    ],
)
def test_invalid_telemetry_environment_is_rejected(
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch, TELEMETRY_VARIABLES)
    monkeypatch.setenv(name, value)
    with pytest.raises(TelemetryConfigurationError, match=message):
        TelemetrySettings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("AC_NODE_BASE_URL", "node.local", "absolute HTTP"),
        ("AC_COMMAND_TIMEOUT_SECONDS", "-1", "greater than zero"),
        ("AC_DEVICE_ID", " ", "must not be empty"),
        ("LOG_LEVEL", "LOUD", "invalid"),
    ],
)
def test_invalid_ac_environment_is_rejected(
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch, AC_VARIABLES)
    monkeypatch.setenv(name, value)
    with pytest.raises(AcConfigurationError, match=message):
        AcSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("API_HOST", " ", "must not be empty"),
        ("API_PORT", "web", "must be an integer"),
        ("API_PORT", "0", "1 through 65535"),
        ("API_PORT", "65536", "1 through 65535"),
        ("API_TELEMETRY_STALE_AFTER_SECONDS", "0", "greater than zero"),
        ("API_COLLECTOR_STALE_AFTER_SECONDS", "0", "greater than zero"),
        ("API_DOCS_ENABLED", "sometimes", "true or false"),
        ("DEVICE_ID", " ", "must not be empty"),
        ("LOG_LEVEL", "LOUD", "invalid"),
    ],
)
def test_invalid_api_environment_is_rejected(
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch, API_VARIABLES)
    monkeypatch.setenv(name, value)
    with pytest.raises(ApiConfigurationError, match=message):
        ApiSettings.from_env()


def test_authenticated_control_requires_all_production_guards(
    monkeypatch,
    tmp_path,
) -> None:
    clear(monkeypatch, API_VARIABLES)
    password_hash = tmp_path / "owner-password.hash"
    password_hash.write_text("$argon2id$test", encoding="utf-8")
    monkeypatch.setenv("AUTH_PASSWORD_HASH_FILE", str(password_hash))
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AC_CONTROL_ENABLED", "true")
    monkeypatch.setenv("API_DOCS_ENABLED", "false")

    settings = ApiSettings.from_env()

    assert settings.auth_enabled is True
    assert settings.ac_control_enabled is True
    assert settings.password_hash_file == password_hash
    assert settings.session_idle_seconds == 86_400
    assert settings.session_absolute_seconds == 604_800
    assert settings.command_rate_limit_per_minute == 6


def test_alert_evaluator_environment_defaults(monkeypatch) -> None:
    clear(monkeypatch, ALERT_VARIABLES)
    settings = AlertSettings.from_env()
    assert str(settings.database_path) == "data/telemetry.db"
    assert settings.device_id == "ac-controller-01"
    assert settings.evaluation_interval_seconds == 30
    assert settings.evaluator_stale_after_seconds == 90
    assert settings.policy.telemetry_suspect_after_seconds == 45
    assert settings.policy.telemetry_alert_after_seconds == 180
    assert settings.policy.edge_min_consecutive_failures == 4
    assert settings.policy.edge_alert_after_seconds == 45
    assert settings.policy.recovery_display_seconds == 300


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ALERT_EVALUATION_INTERVAL_SECONDS", "0", "greater than zero"),
        ("ALERT_TELEMETRY_ALERT_AFTER_SECONDS", "30", "must not be below"),
        ("ALERT_EDGE_MIN_CONSECUTIVE_FAILURES", "0", "greater than zero"),
        ("ALERT_EVALUATOR_STALE_AFTER_SECONDS", "30", "must exceed"),
    ],
)
def test_invalid_alert_evaluator_environment_is_rejected(
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch, ALERT_VARIABLES)
    monkeypatch.setenv(name, value)
    with pytest.raises(AlertConfigurationError, match=message):
        AlertSettings.from_env()


def test_telegram_environment_requires_explicit_enablement_and_secret(
    monkeypatch,
    tmp_path,
) -> None:
    clear(monkeypatch, TELEGRAM_VARIABLES)
    token = tmp_path / "telegram-bot.token"
    token.write_text("123456:secret-token\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token))
    monkeypatch.setenv("TELEGRAM_OWNER_USER_ID", "112233")

    settings = TelegramSettings.from_env()

    assert settings.token_file == token
    assert settings.read_token() == "123456:secret-token"
    assert settings.owner_user_id == 112233
    assert settings.device_id == "ac-controller-01"
    assert settings.command_rate_limit_per_minute == 6
    assert settings.poll_timeout_seconds == 25


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("TELEGRAM_BOT_ENABLED", "false", "must be true"),
        ("TELEGRAM_OWNER_USER_ID", "0", "greater than zero"),
        ("TELEGRAM_POLL_TIMEOUT_SECONDS", "51", "must not exceed"),
    ],
)
def test_invalid_telegram_environment_is_rejected(
    monkeypatch,
    tmp_path,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch, TELEGRAM_VARIABLES)
    token = tmp_path / "telegram-bot.token"
    token.write_text("123456:secret-token\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token))
    monkeypatch.setenv("TELEGRAM_OWNER_USER_ID", "112233")
    monkeypatch.setenv(name, value)
    with pytest.raises(TelegramConfigurationError, match=message):
        TelegramSettings.from_env()


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {
                "API_AUTH_ENABLED": "false",
                "API_AC_CONTROL_ENABLED": "true",
                "API_DOCS_ENABLED": "false",
            },
            "require authentication",
        ),
        (
            {
                "API_AUTH_ENABLED": "true",
                "API_AC_CONTROL_ENABLED": "true",
                "API_DOCS_ENABLED": "true",
            },
            "API_DOCS_ENABLED=false",
        ),
        (
            {
                "API_AUTH_ENABLED": "true",
                "PUBLIC_ORIGIN": "http://rubik-edge-01.local",
            },
            "HTTPS PUBLIC_ORIGIN",
        ),
    ],
)
def test_insecure_authenticated_control_combinations_are_rejected(
    monkeypatch,
    tmp_path,
    values,
    message,
) -> None:
    clear(monkeypatch, API_VARIABLES)
    password_hash = tmp_path / "owner-password.hash"
    password_hash.write_text("$argon2id$test", encoding="utf-8")
    monkeypatch.setenv("AUTH_PASSWORD_HASH_FILE", str(password_hash))
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ApiConfigurationError, match=message):
        ApiSettings.from_env()
