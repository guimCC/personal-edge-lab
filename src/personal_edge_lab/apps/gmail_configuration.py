"""Shared private Gmail credential and retrieval configuration."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personal_edge_lab.apps.configuration import (
    ConfigurationError,
    read_bool,
    read_file_path,
    read_log_level,
    read_port,
    read_positive_float,
    read_positive_int,
)
from personal_edge_lab.infrastructure.gmail.oauth import GMAIL_READONLY_SCOPE

DEFAULT_CLIENT_SECRET_FILE = "/home/ubuntu/personal-edge-lab/secrets/gmail-client.json"
DEFAULT_TOKEN_FILE = "/home/ubuntu/personal-edge-lab/secrets/gmail-oauth/gmail-token.json"
MAX_PRIVATE_JSON_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class GmailAuthorizationSettings:
    client_secret_file: Path
    token_file: Path
    callback_port: int
    log_level: int

    @classmethod
    def from_env(cls) -> GmailAuthorizationSettings:
        client_secret_file = read_file_path(
            "GMAIL_CLIENT_SECRET_FILE",
            DEFAULT_CLIENT_SECRET_FILE,
        )
        token_file = read_file_path("GMAIL_TOKEN_FILE", DEFAULT_TOKEN_FILE)
        validate_gmail_client_secret(client_secret_file)
        validate_gmail_token_target(token_file)
        callback_port = read_port("GMAIL_OAUTH_CALLBACK_PORT", "8765")
        level, _level_name = read_log_level()
        return cls(
            client_secret_file=client_secret_file,
            token_file=token_file,
            callback_port=callback_port,
            log_level=level,
        )


@dataclass(frozen=True, slots=True)
class GmailFetchSettings:
    client_secret_file: Path
    token_file: Path
    timeout_seconds: float
    default_batch_size: int
    max_message_bytes: int
    max_normalized_chars: int
    log_level: int

    @classmethod
    def from_env(cls) -> GmailFetchSettings:
        if not read_bool("GMAIL_READ_ENABLED", "false"):
            raise ConfigurationError("GMAIL_READ_ENABLED must be true for fetch")
        client_secret_file = read_file_path(
            "GMAIL_CLIENT_SECRET_FILE",
            DEFAULT_CLIENT_SECRET_FILE,
        )
        token_file = read_file_path("GMAIL_TOKEN_FILE", DEFAULT_TOKEN_FILE)
        validate_gmail_client_secret(client_secret_file)
        validate_gmail_token(token_file)
        timeout_seconds = read_positive_float("GMAIL_TIMEOUT_SECONDS", "10")
        if timeout_seconds > 60:
            raise ConfigurationError("GMAIL_TIMEOUT_SECONDS must not exceed 60")
        default_batch_size = read_positive_int("GMAIL_DEFAULT_BATCH_SIZE", "10")
        if default_batch_size > 25:
            raise ConfigurationError("GMAIL_DEFAULT_BATCH_SIZE must not exceed 25")
        max_message_bytes = read_positive_int("GMAIL_MAX_MESSAGE_BYTES", "262144")
        if max_message_bytes > 1_048_576:
            raise ConfigurationError("GMAIL_MAX_MESSAGE_BYTES must not exceed 1048576")
        max_normalized_chars = read_positive_int("GMAIL_MAX_NORMALIZED_CHARS", "8000")
        if max_normalized_chars > 8000:
            raise ConfigurationError("GMAIL_MAX_NORMALIZED_CHARS must not exceed 8000")
        level, _level_name = read_log_level()
        return cls(
            client_secret_file=client_secret_file,
            token_file=token_file,
            timeout_seconds=timeout_seconds,
            default_batch_size=default_batch_size,
            max_message_bytes=max_message_bytes,
            max_normalized_chars=max_normalized_chars,
            log_level=level,
        )


def validate_gmail_client_secret(path: Path) -> None:
    value = _read_private_json(path, "GMAIL_CLIENT_SECRET_FILE")
    if set(value) != {"installed"} or not isinstance(value["installed"], dict):
        raise ConfigurationError("GMAIL_CLIENT_SECRET_FILE is not a Desktop OAuth client")
    installed = value["installed"]
    required = {"client_id", "client_secret", "auth_uri", "token_uri", "redirect_uris"}
    if not required.issubset(installed):
        raise ConfigurationError("GMAIL_CLIENT_SECRET_FILE is not a Desktop OAuth client")
    string_keys = required - {"redirect_uris"}
    if not all(isinstance(installed[key], str) and installed[key] for key in string_keys):
        raise ConfigurationError("GMAIL_CLIENT_SECRET_FILE is not a Desktop OAuth client")
    redirect_uris = installed["redirect_uris"]
    if not isinstance(redirect_uris, list) or not any(
        isinstance(uri, str)
        and (uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1"))
        for uri in redirect_uris
    ):
        raise ConfigurationError("GMAIL_CLIENT_SECRET_FILE lacks a loopback redirect")


def validate_gmail_token(path: Path) -> None:
    value = _read_private_json(path, "GMAIL_TOKEN_FILE")
    required = {"token", "refresh_token", "token_uri", "client_id", "client_secret", "scopes"}
    if not required.issubset(value):
        raise ConfigurationError("GMAIL_TOKEN_FILE contains invalid credentials")
    if not all(isinstance(value[key], str) and bool(value[key]) for key in required - {"scopes"}):
        raise ConfigurationError("GMAIL_TOKEN_FILE contains invalid credentials")
    scopes = value["scopes"]
    if not isinstance(scopes, list) or scopes != [GMAIL_READONLY_SCOPE]:
        raise ConfigurationError("GMAIL_TOKEN_FILE must contain only the Gmail read-only scope")


def validate_gmail_token_target(path: Path) -> None:
    _validate_absolute_path(path, "GMAIL_TOKEN_FILE")
    if path.exists():
        _validate_private_metadata(path, "GMAIL_TOKEN_FILE")
    elif not path.parent.is_dir():
        raise ConfigurationError("GMAIL_TOKEN_FILE parent directory must exist")


def validate_gmail_token_directory(path: Path) -> None:
    """Require the API-refresh directory to be private and owner controlled."""

    parent = path.parent
    if parent.is_symlink():
        raise ConfigurationError("GMAIL_TOKEN_FILE parent must not be a symbolic link")
    try:
        metadata = parent.stat()
    except OSError as error:
        raise ConfigurationError("GMAIL_TOKEN_FILE parent must be a private directory") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ConfigurationError("GMAIL_TOKEN_FILE parent must be a private directory")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ConfigurationError("GMAIL_TOKEN_FILE parent must have mode 0700")
    if metadata.st_uid != os.geteuid():
        raise ConfigurationError("GMAIL_TOKEN_FILE parent must be owned by the current user")


def _read_private_json(path: Path, setting: str) -> dict[str, Any]:
    _validate_absolute_path(path, setting)
    _validate_private_metadata(path, setting)
    try:
        if path.stat().st_size > MAX_PRIVATE_JSON_BYTES:
            raise ConfigurationError(f"{setting} is too large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except ConfigurationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"{setting} must contain valid private JSON") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{setting} must contain a JSON object")
    return value


def _validate_absolute_path(path: Path, setting: str) -> None:
    if not path.is_absolute():
        raise ConfigurationError(f"{setting} must be an absolute path")
    if path.is_symlink():
        raise ConfigurationError(f"{setting} must not be a symbolic link")


def _validate_private_metadata(path: Path, setting: str) -> None:
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
    if not os.access(path, os.R_OK):
        raise ConfigurationError(f"{setting} must be readable")
