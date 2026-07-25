"""Environment-based telemetry collector configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from personal_edge_lab.apps.configuration import (
    ConfigurationError,
    read_file_path,
    read_http_url,
    read_log_level,
    read_nonblank,
    read_positive_float,
)


@dataclass(frozen=True, slots=True)
class Settings:
    edge_node_base_url: str
    temperature_endpoint: str
    collection_interval_seconds: float
    http_timeout_seconds: float
    database_path: Path
    log_level: int
    device_id: str

    @classmethod
    def from_env(cls) -> Settings:
        base_url = read_http_url("EDGE_NODE_BASE_URL", "http://ac-controller-01.local")

        endpoint = os.getenv("TEMPERATURE_ENDPOINT", "/temperature")
        if not endpoint.startswith("/"):
            raise ConfigurationError("TEMPERATURE_ENDPOINT must start with '/'")

        interval = read_positive_float("COLLECTION_INTERVAL_SECONDS", "15")
        timeout = read_positive_float("HTTP_TIMEOUT_SECONDS", "5")
        database_path = read_file_path("DATABASE_PATH", "./data/telemetry.db")
        level, _level_name = read_log_level()
        device_id = read_nonblank("DEVICE_ID", "ac-controller-01")

        return cls(base_url, endpoint, interval, timeout, database_path, level, device_id)

    @property
    def temperature_url(self) -> str:
        return f"{self.edge_node_base_url}{self.temperature_endpoint}"
