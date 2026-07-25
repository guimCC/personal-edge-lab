"""Telemetry collection use cases."""

from personal_edge_lab.modules.telemetry.collect_temperature import (
    CollectionReceipt,
    CollectTemperature,
)
from personal_edge_lab.modules.telemetry.collector_status import CollectorStatusMonitor
from personal_edge_lab.modules.telemetry.queries import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    CollectorHealth,
    CollectorHealthStatus,
    EdgeNodeHealth,
    EdgeNodeHealthStatus,
    GetLatestTemperature,
    GetOperationalHealth,
    GetTelemetryHealth,
    GetTemperatureSeries,
    ListTemperatureHistory,
    OperationalHealth,
    TelemetryFreshness,
    TelemetryHealth,
    TelemetryQueryError,
    TelemetrySeries,
    TelemetryWindow,
)

__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "MAX_HISTORY_LIMIT",
    "CollectorHealth",
    "CollectorHealthStatus",
    "CollectorStatusMonitor",
    "CollectTemperature",
    "CollectionReceipt",
    "EdgeNodeHealth",
    "EdgeNodeHealthStatus",
    "GetLatestTemperature",
    "GetOperationalHealth",
    "GetTelemetryHealth",
    "GetTemperatureSeries",
    "ListTemperatureHistory",
    "OperationalHealth",
    "TelemetryFreshness",
    "TelemetryHealth",
    "TelemetryQueryError",
    "TelemetrySeries",
    "TelemetryWindow",
]
