"""Telemetry collection use cases."""

from personal_edge_lab.modules.telemetry.collect_temperature import (
    CollectionReceipt,
    CollectTemperature,
)
from personal_edge_lab.modules.telemetry.queries import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    GetLatestTemperature,
    GetTelemetryHealth,
    ListTemperatureHistory,
    TelemetryFreshness,
    TelemetryHealth,
    TelemetryQueryError,
)

__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "MAX_HISTORY_LIMIT",
    "CollectTemperature",
    "CollectionReceipt",
    "GetLatestTemperature",
    "GetTelemetryHealth",
    "ListTemperatureHistory",
    "TelemetryFreshness",
    "TelemetryHealth",
    "TelemetryQueryError",
]
