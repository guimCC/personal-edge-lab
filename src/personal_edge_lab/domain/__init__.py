"""Pure domain models and rules."""

from personal_edge_lab.domain.ac import (
    AcMode,
    AcState,
    CommandAuditEntry,
    CommandExecution,
    CommandOutcome,
    CommandResult,
    FanSpeed,
    VerticalVane,
    canonical_json,
)
from personal_edge_lab.domain.ac import (
    ValidationError as AcValidationError,
)
from personal_edge_lab.domain.telemetry import (
    TemperatureReading,
)
from personal_edge_lab.domain.telemetry import (
    ValidationError as TemperatureValidationError,
)

__all__ = [
    "AcMode",
    "AcState",
    "AcValidationError",
    "CommandAuditEntry",
    "CommandExecution",
    "CommandOutcome",
    "CommandResult",
    "FanSpeed",
    "TemperatureReading",
    "TemperatureValidationError",
    "VerticalVane",
    "canonical_json",
]
