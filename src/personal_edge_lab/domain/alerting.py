"""Durable operational alert domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AlertType(StrEnum):
    TELEMETRY_STALE = "telemetry_stale"
    EDGE_UNAVAILABLE = "edge_unavailable"


class AlertLifecycleState(StrEnum):
    HEALTHY = "healthy"
    SUSPECT = "suspect"
    ALERTING = "alerting"
    RECOVERED = "recovered"


class AlertIncidentStatus(StrEnum):
    ACTIVE = "active"
    RECOVERED = "recovered"


class AlertSignalStatus(StrEnum):
    GOOD = "good"
    BAD = "bad"
    UNKNOWN = "unknown"


class EvaluatorOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    telemetry_suspect_after_seconds: float
    telemetry_alert_after_seconds: float
    edge_min_consecutive_failures: int
    edge_alert_after_seconds: float
    recovery_display_seconds: float

    def __post_init__(self) -> None:
        if self.telemetry_suspect_after_seconds <= 0:
            raise ValueError("telemetry suspect threshold must be greater than zero")
        if self.telemetry_alert_after_seconds < self.telemetry_suspect_after_seconds:
            raise ValueError("telemetry alert threshold must not be below suspect threshold")
        if self.edge_min_consecutive_failures <= 0:
            raise ValueError("edge failure count must be greater than zero")
        if self.edge_alert_after_seconds <= 0:
            raise ValueError("edge alert threshold must be greater than zero")
        if self.recovery_display_seconds <= 0:
            raise ValueError("recovery display duration must be greater than zero")


@dataclass(frozen=True, slots=True)
class AlertSignal:
    status: AlertSignalStatus
    alert_ready: bool
    evidence_category: str
    evidence_message: str


@dataclass(frozen=True, slots=True)
class AlertState:
    device_id: str
    alert_type: AlertType
    lifecycle: AlertLifecycleState
    suspect_started_at: datetime | None
    active_incident_id: int | None
    recovered_at: datetime | None
    recovery_display_until: datetime | None
    last_observed_at: datetime
    evidence_category: str
    evidence_message: str


@dataclass(frozen=True, slots=True)
class AlertIncident:
    id: int
    device_id: str
    alert_type: AlertType
    status: AlertIncidentStatus
    suspect_started_at: datetime
    alerting_at: datetime
    recovered_at: datetime | None
    last_observed_at: datetime
    evidence_category: str
    evidence_message: str


@dataclass(frozen=True, slots=True)
class AlertTransition:
    id: int
    incident_id: int | None
    device_id: str
    alert_type: AlertType
    from_state: AlertLifecycleState
    to_state: AlertLifecycleState
    transitioned_at: datetime
    evidence_category: str
    evidence_message: str


@dataclass(frozen=True, slots=True)
class AlertEvaluatorRuntime:
    last_started_at: datetime
    last_finished_at: datetime | None
    last_outcome: EvaluatorOutcome | None
    last_error_category: str | None
    last_error_message: str | None


@dataclass(frozen=True, slots=True)
class AlertEvaluationResult:
    device_id: str
    evaluated_at: datetime
    states: tuple[AlertState, ...]
    transitions: tuple[AlertTransition, ...]
