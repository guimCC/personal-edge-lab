"""Environment configuration for the local language-model diagnostic CLI."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from personal_edge_lab.apps.configuration import (
    ConfigurationError as ConfigurationError,
)
from personal_edge_lab.apps.configuration import (
    read_bool,
    read_file_path,
    read_log_level,
    read_nonblank,
    read_positive_float,
    read_positive_int,
)

MODEL_ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class HealthSettings:
    base_url: str
    timeout_seconds: float
    log_level: int

    @classmethod
    def from_env(cls) -> HealthSettings:
        base_url = _read_origin_url()
        timeout = read_positive_float("LOCAL_LLM_HEALTH_TIMEOUT_SECONDS", "5")
        if timeout > 30:
            raise ConfigurationError("LOCAL_LLM_HEALTH_TIMEOUT_SECONDS must not exceed 30")
        level, _level_name = read_log_level()
        return cls(base_url=base_url, timeout_seconds=timeout, log_level=level)


@dataclass(frozen=True, slots=True)
class CompletionSettings:
    base_url: str
    api_key_file: Path
    api_key: str = field(repr=False)
    model_alias: str
    timeout_seconds: float
    max_input_chars: int
    max_output_tokens: int
    max_concurrency: int
    queue_timeout_seconds: float
    log_level: int

    @classmethod
    def from_env(cls) -> CompletionSettings:
        if not read_bool("LOCAL_LLM_ENABLED", "false"):
            raise ConfigurationError("LOCAL_LLM_ENABLED must be true for complete")
        base_url = _read_origin_url()
        api_key_file = read_file_path(
            "LOCAL_LLM_API_KEY_FILE",
            "/home/ubuntu/personal-edge-lab/secrets/unoq-ai-01.key",
        )
        api_key = _read_private_key(api_key_file, "LOCAL_LLM_API_KEY_FILE")
        model_alias = read_nonblank("LOCAL_LLM_MODEL", "qwen3-1.7b-q4-k-m")
        if MODEL_ALIAS_PATTERN.fullmatch(model_alias) is None:
            raise ConfigurationError("LOCAL_LLM_MODEL is not a valid logical model alias")
        timeout = read_positive_float("LOCAL_LLM_TIMEOUT_SECONDS", "60")
        if timeout > 300:
            raise ConfigurationError("LOCAL_LLM_TIMEOUT_SECONDS must not exceed 300")
        max_input_chars = read_positive_int("LOCAL_LLM_MAX_INPUT_CHARS", "512")
        if max_input_chars > 4096:
            raise ConfigurationError("LOCAL_LLM_MAX_INPUT_CHARS must not exceed 4096")
        max_output_tokens = read_positive_int("LOCAL_LLM_MAX_OUTPUT_TOKENS", "32")
        if max_output_tokens > 256:
            raise ConfigurationError("LOCAL_LLM_MAX_OUTPUT_TOKENS must not exceed 256")
        max_concurrency = read_positive_int("LOCAL_LLM_MAX_CONCURRENCY", "1")
        if max_concurrency != 1:
            raise ConfigurationError("LOCAL_LLM_MAX_CONCURRENCY must be exactly 1")
        queue_timeout = read_positive_float("LOCAL_LLM_QUEUE_TIMEOUT_SECONDS", "60")
        if queue_timeout > 300:
            raise ConfigurationError("LOCAL_LLM_QUEUE_TIMEOUT_SECONDS must not exceed 300")
        level, _level_name = read_log_level()
        return cls(
            base_url=base_url,
            api_key_file=api_key_file,
            api_key=api_key,
            model_alias=model_alias,
            timeout_seconds=timeout,
            max_input_chars=max_input_chars,
            max_output_tokens=max_output_tokens,
            max_concurrency=max_concurrency,
            queue_timeout_seconds=queue_timeout,
            log_level=level,
        )


@dataclass(frozen=True, slots=True)
class LangfuseSettings:
    enabled: bool
    base_url: str
    public_key_file: Path | None
    public_key: str | None = field(repr=False)
    secret_key_file: Path | None
    secret_key: str | None = field(repr=False)
    timeout_seconds: float
    log_level: int

    @classmethod
    def from_env(cls, *, require_enabled: bool = False) -> LangfuseSettings:
        enabled = read_bool("LANGFUSE_ENABLED", "false")
        if require_enabled and not enabled:
            raise ConfigurationError("LANGFUSE_ENABLED must be true for prompt-publish")
        timeout = read_positive_float("LANGFUSE_TIMEOUT_SECONDS", "2")
        if timeout > 30:
            raise ConfigurationError("LANGFUSE_TIMEOUT_SECONDS must not exceed 30")
        level, _level_name = read_log_level()
        if not enabled:
            return cls(
                enabled=False,
                base_url="https://cloud.langfuse.com",
                public_key_file=None,
                public_key=None,
                secret_key_file=None,
                secret_key=None,
                timeout_seconds=timeout,
                log_level=level,
            )
        base_url = _read_langfuse_url()
        public_key_file = read_file_path(
            "LANGFUSE_PUBLIC_KEY_FILE",
            "/home/ubuntu/personal-edge-lab/secrets/langfuse-public.key",
        )
        secret_key_file = read_file_path(
            "LANGFUSE_SECRET_KEY_FILE",
            "/home/ubuntu/personal-edge-lab/secrets/langfuse-secret.key",
        )
        return cls(
            enabled=True,
            base_url=base_url,
            public_key_file=public_key_file,
            public_key=_read_private_key(public_key_file, "LANGFUSE_PUBLIC_KEY_FILE"),
            secret_key_file=secret_key_file,
            secret_key=_read_private_key(secret_key_file, "LANGFUSE_SECRET_KEY_FILE"),
            timeout_seconds=timeout,
            log_level=level,
        )


@dataclass(frozen=True, slots=True)
class TriageSettings:
    completion: CompletionSettings
    langfuse: LangfuseSettings

    @classmethod
    def from_env(cls) -> TriageSettings:
        return cls(
            completion=CompletionSettings.from_env(),
            langfuse=LangfuseSettings.from_env(),
        )


def _read_origin_url() -> str:
    value = read_nonblank("LOCAL_LLM_BASE_URL", "http://unoq-ai-01.local:8080").rstrip("/")
    parsed = urlparse(value)
    try:
        parsed_port = parsed.port
    except ValueError as error:
        raise ConfigurationError("LOCAL_LLM_BASE_URL must be an origin-only HTTP(S) URL") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or any(character.isspace() for character in parsed.netloc)
        or (parsed_port is not None and not 1 <= parsed_port <= 65535)
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("LOCAL_LLM_BASE_URL must be an origin-only HTTP(S) URL")
    return value


def _read_langfuse_url() -> str:
    value = read_nonblank("LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/")
    parsed = urlparse(value)
    try:
        parsed_port = parsed.port
    except ValueError as error:
        raise ConfigurationError("LANGFUSE_BASE_URL must be an origin-only HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or any(character.isspace() for character in parsed.netloc)
        or (parsed_port is not None and not 1 <= parsed_port <= 65535)
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("LANGFUSE_BASE_URL must be an origin-only HTTPS URL")
    return value


def _read_private_key(path: Path, setting: str) -> str:
    if not path.is_absolute():
        raise ConfigurationError(f"{setting} must be an absolute path")
    if path.is_symlink():
        raise ConfigurationError(f"{setting} must not be a symbolic link")
    try:
        metadata = path.stat()
    except OSError as error:
        raise ConfigurationError(f"{setting} must be a readable private file") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"{setting} must be a regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ConfigurationError(f"{setting} must have mode 0600")
    if metadata.st_uid != os.geteuid():
        raise ConfigurationError(f"{setting} must be owned by the current user")
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"{setting} must be readable") from error
    lines = value.splitlines()
    if (
        len(lines) != 1
        or not 32 <= len(lines[0]) <= 256
        or any(character.isspace() for character in lines[0])
    ):
        raise ConfigurationError(f"{setting} contains an invalid key")
    return lines[0]
