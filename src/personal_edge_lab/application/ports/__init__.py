"""Protocols implemented by infrastructure adapters."""

from personal_edge_lab.application.ports.ac import AcController, CommandAuditRepository
from personal_edge_lab.application.ports.telemetry import (
    TelemetryRepository,
    TemperatureSource,
    TemperatureSourceError,
)

__all__ = [
    "AcController",
    "CommandAuditRepository",
    "TemperatureSource",
    "TemperatureSourceError",
    "TelemetryRepository",
]
