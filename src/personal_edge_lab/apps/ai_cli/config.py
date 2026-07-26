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
        api_key = _read_private_key(api_key_file)
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
        level, _level_name = read_log_level()
        return cls(
            base_url=base_url,
            api_key_file=api_key_file,
            api_key=api_key,
            model_alias=model_alias,
            timeout_seconds=timeout,
            max_input_chars=max_input_chars,
            max_output_tokens=max_output_tokens,
            log_level=level,
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


def _read_private_key(path: Path) -> str:
    if not path.is_absolute():
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE must be an absolute path")
    if path.is_symlink():
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE must not be a symbolic link")
    try:
        metadata = path.stat()
    except OSError as error:
        raise ConfigurationError(
            "LOCAL_LLM_API_KEY_FILE must be a readable private file"
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE must be a regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE must have mode 0600")
    if metadata.st_uid != os.geteuid():
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE must be owned by the current user")
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE must be readable") from error
    lines = value.splitlines()
    if (
        len(lines) != 1
        or not 32 <= len(lines[0]) <= 256
        or any(character.isspace() for character in lines[0])
    ):
        raise ConfigurationError("LOCAL_LLM_API_KEY_FILE contains an invalid key")
    return lines[0]
