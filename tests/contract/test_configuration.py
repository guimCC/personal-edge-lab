from __future__ import annotations

import logging

import pytest

from personal_edge_lab.apps.ac_cli.config import (
    ConfigurationError as AcConfigurationError,
)
from personal_edge_lab.apps.ac_cli.config import Settings as AcSettings
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
