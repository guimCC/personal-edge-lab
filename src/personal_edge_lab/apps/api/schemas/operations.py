"""Operational health and durable alert contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from personal_edge_lab.apps.api.schemas.common import ApiModel
from personal_edge_lab.domain.alerting import AlertIncident, AlertState
from personal_edge_lab.modules.alerting import AlertOverview
from personal_edge_lab.modules.platform_status import PlatformHealth
from personal_edge_lab.modules.telemetry import (
    CollectorHealth,
    EdgeNodeHealth,
    TelemetryHealth,
)


class DatabaseHealthResponse(ApiModel):
    status: Literal["healthy"] = "healthy"


class TelemetryHealthResponse(ApiModel):
    status: Literal["fresh", "stale", "no_data"]
    device_id: str
    last_received_at_utc: datetime | None
    age_seconds: float | None
    stale_after_seconds: float

    @classmethod
    def from_application(cls, health: TelemetryHealth) -> TelemetryHealthResponse:
        return cls(
            status=health.status.value,
            device_id=health.device_id,
            last_received_at_utc=health.last_received_at,
            age_seconds=health.age_seconds,
            stale_after_seconds=health.stale_after_seconds,
        )


class CollectorHealthResponse(ApiModel):
    status: Literal["running", "stopped", "stale", "no_data"]
    device_id: str
    process_started_at_utc: datetime | None
    heartbeat_at_utc: datetime | None
    heartbeat_age_seconds: float | None
    stale_after_seconds: float
    stopped_at_utc: datetime | None
    last_attempt_at_utc: datetime | None
    last_success_at_utc: datetime | None
    consecutive_failures: int

    @classmethod
    def from_application(cls, health: CollectorHealth) -> CollectorHealthResponse:
        return cls(
            status=health.status,
            device_id=health.device_id,
            process_started_at_utc=health.process_started_at,
            heartbeat_at_utc=health.heartbeat_at,
            heartbeat_age_seconds=health.heartbeat_age_seconds,
            stale_after_seconds=health.stale_after_seconds,
            stopped_at_utc=health.stopped_at,
            last_attempt_at_utc=health.last_attempt_at,
            last_success_at_utc=health.last_success_at,
            consecutive_failures=health.consecutive_failures,
        )


class EdgeNodeHealthResponse(ApiModel):
    status: Literal["reachable", "unreachable", "unknown"]
    device_id: str
    last_attempt_at_utc: datetime | None
    last_success_at_utc: datetime | None
    last_failure_at_utc: datetime | None
    last_failure_category: str | None
    last_failure_message: str | None

    @classmethod
    def from_application(cls, health: EdgeNodeHealth) -> EdgeNodeHealthResponse:
        return cls(
            status=health.status,
            device_id=health.device_id,
            last_attempt_at_utc=health.last_attempt_at,
            last_success_at_utc=health.last_success_at,
            last_failure_at_utc=health.last_failure_at,
            last_failure_category=health.last_failure_category,
            last_failure_message=health.last_failure_message,
        )


class AlertHealthResponse(ApiModel):
    status: Literal["healthy", "suspect", "alerting", "recovered", "unknown"]
    active_count: int
    suspect_count: int
    latest_transition_at_utc: datetime | None
    evaluator_last_run_at_utc: datetime | None
    evaluator_age_seconds: float | None

    @classmethod
    def from_application(cls, overview: AlertOverview) -> AlertHealthResponse:
        return cls(
            status=overview.status,
            active_count=overview.active_count,
            suspect_count=overview.suspect_count,
            latest_transition_at_utc=overview.latest_transition_at,
            evaluator_last_run_at_utc=overview.evaluator_last_run_at,
            evaluator_age_seconds=overview.evaluator_age_seconds,
        )


class HealthResponse(ApiModel):
    status: Literal["healthy", "degraded"]
    version: str
    checked_at_utc: datetime
    database: DatabaseHealthResponse
    telemetry: TelemetryHealthResponse
    collector: CollectorHealthResponse
    edge_node: EdgeNodeHealthResponse
    alerts: AlertHealthResponse

    @classmethod
    def from_application(
        cls,
        health: PlatformHealth,
        *,
        version: str,
    ) -> HealthResponse:
        return cls(
            status=health.status,
            version=version,
            checked_at_utc=health.checked_at,
            database=DatabaseHealthResponse(),
            telemetry=TelemetryHealthResponse.from_application(health.telemetry),
            collector=CollectorHealthResponse.from_application(health.collector),
            edge_node=EdgeNodeHealthResponse.from_application(health.edge_node),
            alerts=AlertHealthResponse.from_application(health.alerts),
        )


class AlertStateResponse(ApiModel):
    device_id: str
    alert_type: Literal["telemetry_stale", "edge_unavailable"]
    lifecycle: Literal["healthy", "suspect", "alerting", "recovered"]
    suspect_started_at_utc: datetime | None
    active_incident_id: int | None
    recovered_at_utc: datetime | None
    recovery_display_until_utc: datetime | None
    last_observed_at_utc: datetime
    evidence_category: str
    evidence_message: str

    @classmethod
    def from_domain(cls, state: AlertState) -> AlertStateResponse:
        return cls(
            device_id=state.device_id,
            alert_type=state.alert_type,
            lifecycle=state.lifecycle,
            suspect_started_at_utc=state.suspect_started_at,
            active_incident_id=state.active_incident_id,
            recovered_at_utc=state.recovered_at,
            recovery_display_until_utc=state.recovery_display_until,
            last_observed_at_utc=state.last_observed_at,
            evidence_category=state.evidence_category,
            evidence_message=state.evidence_message,
        )


class AlertIncidentResponse(ApiModel):
    id: int
    device_id: str
    alert_type: Literal["telemetry_stale", "edge_unavailable"]
    status: Literal["active", "recovered"]
    suspect_started_at_utc: datetime
    alerting_at_utc: datetime
    recovered_at_utc: datetime | None
    last_observed_at_utc: datetime
    duration_seconds: float
    evidence_category: str
    evidence_message: str

    @classmethod
    def from_domain(
        cls,
        incident: AlertIncident,
        *,
        checked_at: datetime,
    ) -> AlertIncidentResponse:
        ended_at = incident.recovered_at or checked_at
        return cls(
            id=incident.id,
            device_id=incident.device_id,
            alert_type=incident.alert_type,
            status=incident.status,
            suspect_started_at_utc=incident.suspect_started_at,
            alerting_at_utc=incident.alerting_at,
            recovered_at_utc=incident.recovered_at,
            last_observed_at_utc=incident.last_observed_at,
            duration_seconds=max(0.0, (ended_at - incident.alerting_at).total_seconds()),
            evidence_category=incident.evidence_category,
            evidence_message=incident.evidence_message,
        )


class AlertListResponse(ApiModel):
    device_id: str
    status: Literal["healthy", "suspect", "alerting", "recovered", "unknown"]
    evaluator_last_run_at_utc: datetime | None
    evaluator_age_seconds: float | None
    count: int
    limit: int
    states: list[AlertStateResponse]
    incidents: list[AlertIncidentResponse]

    @classmethod
    def from_application(
        cls,
        overview: AlertOverview,
        *,
        checked_at: datetime,
    ) -> AlertListResponse:
        incidents = [
            AlertIncidentResponse.from_domain(incident, checked_at=checked_at)
            for incident in overview.incidents
        ]
        return cls(
            device_id=overview.device_id,
            status=overview.status,
            evaluator_last_run_at_utc=overview.evaluator_last_run_at,
            evaluator_age_seconds=overview.evaluator_age_seconds,
            count=len(incidents),
            limit=overview.limit,
            states=[AlertStateResponse.from_domain(state) for state in overview.states],
            incidents=incidents,
        )


class LivenessResponse(ApiModel):
    status: Literal["alive"] = "alive"
    version: str
