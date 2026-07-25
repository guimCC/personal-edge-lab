"""Environment-based AC command configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personal_edge_lab.apps.configuration import ConfigurationError as ConfigurationError
from personal_edge_lab.apps.configuration import (
    read_file_path,
    read_http_url,
    read_log_level,
    read_nonblank,
    read_positive_float,
)


@dataclass(frozen=True, slots=True)
class Settings:
    node_base_url: str
    command_timeout_seconds: float
    database_path: Path
    log_level: int
    device_id: str

    @classmethod
    def from_env(cls) -> Settings:
        base_url = read_http_url("AC_NODE_BASE_URL", "http://ac-controller-01.local")
        timeout = read_positive_float("AC_COMMAND_TIMEOUT_SECONDS", "5")
        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        level, _level_name = read_log_level()
        device_id = read_nonblank("AC_DEVICE_ID", "ac-controller-01")

        return cls(base_url, timeout, database_path, level, device_id)
