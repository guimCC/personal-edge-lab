from __future__ import annotations

import logging
import os

import pytest

from personal_edge_lab.apps.ai_cli import config
from personal_edge_lab.apps.ai_cli.config import (
    CompletionSettings,
    ConfigurationError,
    HealthSettings,
)

AI_VARIABLES = (
    "LOCAL_LLM_ENABLED",
    "LOCAL_LLM_BASE_URL",
    "LOCAL_LLM_API_KEY_FILE",
    "LOCAL_LLM_MODEL",
    "LOCAL_LLM_HEALTH_TIMEOUT_SECONDS",
    "LOCAL_LLM_TIMEOUT_SECONDS",
    "LOCAL_LLM_MAX_INPUT_CHARS",
    "LOCAL_LLM_MAX_OUTPUT_TOKENS",
    "LOG_LEVEL",
)


def clear(monkeypatch) -> None:
    for name in AI_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def private_key(tmp_path, value: str = "a" * 64):
    path = tmp_path / "unoq.key"
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def configure_completion(monkeypatch, tmp_path) -> object:
    key = private_key(tmp_path)
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", str(key))
    return key


def test_health_defaults_do_not_require_enablement_or_key(monkeypatch) -> None:
    clear(monkeypatch)
    settings = HealthSettings.from_env()
    assert settings.base_url == "http://unoq-ai-01.local:8080"
    assert settings.timeout_seconds == 5
    assert settings.log_level == logging.INFO


def test_completion_defaults_with_private_key(monkeypatch, tmp_path) -> None:
    clear(monkeypatch)
    key = configure_completion(monkeypatch, tmp_path)
    settings = CompletionSettings.from_env()
    assert settings.api_key_file == key
    assert settings.api_key == "a" * 64
    assert "a" * 64 not in repr(settings)
    assert settings.model_alias == "qwen3-1.7b-q4-k-m"
    assert settings.timeout_seconds == 60
    assert settings.max_input_chars == 512
    assert settings.max_output_tokens == 32


def test_completion_requires_explicit_enablement(monkeypatch) -> None:
    clear(monkeypatch)
    with pytest.raises(ConfigurationError, match="must be true"):
        CompletionSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("LOCAL_LLM_BASE_URL", "uno.local:8080", "origin-only"),
        ("LOCAL_LLM_BASE_URL", "http://user:secret@uno.local", "origin-only"),
        ("LOCAL_LLM_BASE_URL", "http://uno.local/path", "origin-only"),
        ("LOCAL_LLM_BASE_URL", "http://uno.local:bad", "origin-only"),
        ("LOCAL_LLM_BASE_URL", "http://uno local:8080", "origin-only"),
        ("LOCAL_LLM_HEALTH_TIMEOUT_SECONDS", "31", "must not exceed 30"),
    ],
)
def test_invalid_health_configuration(
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError, match=message):
        HealthSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("LOCAL_LLM_MODEL", "Bad Model", "logical model alias"),
        ("LOCAL_LLM_TIMEOUT_SECONDS", "301", "must not exceed 300"),
        ("LOCAL_LLM_MAX_INPUT_CHARS", "4097", "must not exceed 4096"),
        ("LOCAL_LLM_MAX_OUTPUT_TOKENS", "257", "must not exceed 256"),
    ],
)
def test_invalid_completion_bounds(
    monkeypatch,
    tmp_path,
    name: str,
    value: str,
    message: str,
) -> None:
    clear(monkeypatch)
    configure_completion(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError, match=message):
        CompletionSettings.from_env()


def test_relative_key_path_is_rejected(monkeypatch) -> None:
    clear(monkeypatch)
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", "secrets/key")
    with pytest.raises(ConfigurationError, match="absolute"):
        CompletionSettings.from_env()


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "readable private file"),
        ("directory", "must name a file"),
        ("symlink", "symbolic link"),
        ("mode", "mode 0600"),
        ("multiline", "invalid key"),
        ("whitespace", "invalid key"),
        ("short", "invalid key"),
    ],
)
def test_invalid_key_file(
    monkeypatch,
    tmp_path,
    kind: str,
    message: str,
) -> None:
    clear(monkeypatch)
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    path = tmp_path / "key"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = private_key(tmp_path)
        path.symlink_to(target)
    elif kind == "mode":
        path.write_text(f"{'a' * 64}\n", encoding="utf-8")
        path.chmod(0o644)
    elif kind == "multiline":
        path.write_text(f"{'a' * 64}\n{'b' * 64}\n", encoding="utf-8")
        path.chmod(0o600)
    elif kind == "whitespace":
        path.write_text(f"{'a' * 32} {'b' * 32}\n", encoding="utf-8")
        path.chmod(0o600)
    elif kind == "short":
        path.write_text("short\n", encoding="utf-8")
        path.chmod(0o600)
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", str(path))
    with pytest.raises(ConfigurationError, match=message):
        CompletionSettings.from_env()


def test_wrong_key_owner_is_rejected(monkeypatch, tmp_path) -> None:
    clear(monkeypatch)
    key = configure_completion(monkeypatch, tmp_path)
    current_uid = os.geteuid()
    monkeypatch.setattr(config.os, "geteuid", lambda: current_uid + 1)
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", str(key))
    with pytest.raises(ConfigurationError, match="owned"):
        CompletionSettings.from_env()


def test_unreadable_key_is_rejected(monkeypatch, tmp_path) -> None:
    clear(monkeypatch)
    configure_completion(monkeypatch, tmp_path)

    def deny_read(*_args, **_kwargs):
        raise PermissionError

    monkeypatch.setattr(config.Path, "read_text", deny_read)
    with pytest.raises(ConfigurationError, match="must be readable"):
        CompletionSettings.from_env()


def test_key_value_is_absent_from_validation_error(monkeypatch, tmp_path) -> None:
    clear(monkeypatch)
    secret = "never-log-this-secret-key-value"
    key = private_key(tmp_path, secret)
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("LOCAL_LLM_API_KEY_FILE", str(key))
    with pytest.raises(ConfigurationError) as captured:
        CompletionSettings.from_env()
    assert secret not in str(captured.value)
