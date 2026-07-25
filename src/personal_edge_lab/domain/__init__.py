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
from personal_edge_lab.domain.auth import AuthenticatedSession, LoginThrottle, SessionRecord
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
    "AuthenticatedSession",
    "CommandAuditEntry",
    "CommandExecution",
    "CommandOutcome",
    "CommandResult",
    "FanSpeed",
    "LoginThrottle",
    "SessionRecord",
    "TemperatureReading",
    "TemperatureValidationError",
    "VerticalVane",
    "canonical_json",
]
