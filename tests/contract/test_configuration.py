from __future__ import annotations

import logging

import pytest

from personal_edge_lab.apps.ac_cli.config import (
    ConfigurationError as AcConfigurationError,
)
from personal_edge_lab.apps.ac_cli.config import Settings as AcSettings
from personal_edge_lab.apps.api.config import (
    ConfigurationError as ApiConfigurationError,
)
from personal_edge_lab.apps.api.config import Settings as ApiSettings
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
    "API_DOCS_ENABLED",
    "DATABASE_PATH",
    "DEVICE_ID",
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
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.telemetry_stale_after_seconds == 45
    assert settings.docs_enabled is True
    assert str(settings.database_path) == "data/telemetry.db"
    assert settings.device_id == "ac-controller-01"
    assert settings.log_level == logging.INFO
    assert settings.log_level_name == "INFO"


def test_api_environment_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8080")
    monkeypatch.setenv("API_TELEMETRY_STALE_AFTER_SECONDS", "60.5")
    monkeypatch.setenv("API_DOCS_ENABLED", "off")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("DEVICE_ID", "sensor-7")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = ApiSettings.from_env()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.telemetry_stale_after_seconds == 60.5
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
