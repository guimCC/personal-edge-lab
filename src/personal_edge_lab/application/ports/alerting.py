"""Operational alert persistence ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from personal_edge_lab.domain.alerting import (
    AlertEvaluatorRuntime,
    AlertIncident,
    AlertIncidentStatus,
    AlertLifecycleState,
    AlertState,
    AlertTransition,
    AlertType,
)
from personal_edge_lab.domain.notifications import OperationalNotification
from personal_edge_lab.domain.telemetry import CollectorRuntimeStatus, TemperatureReading


class AlertEvaluationRepository(Protocol):
    def __enter__(self) -> AlertEvaluationRepository: ...

    def __exit__(self, *args: object) -> None: ...

    def begin_evaluation(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def record_evaluator_started(self, started_at: datetime) -> None: ...

    def record_evaluator_success(self, finished_at: datetime) -> None: ...

    def record_evaluator_failure(
        self,
        finished_at: datetime,
        *,
        category: str,
        message: str,
    ) -> None: ...

    def latest_temperature(self, device_id: str) -> TemperatureReading | None: ...

    def collector_status(self, device_id: str) -> CollectorRuntimeStatus | None: ...

    def get_state(self, device_id: str, alert_type: AlertType) -> AlertState | None: ...

    def save_state(self, state: AlertState) -> None: ...

    def get_incident(self, incident_id: int) -> AlertIncident | None: ...

    def create_incident(
        self,
        *,
        device_id: str,
        alert_type: AlertType,
        suspect_started_at: datetime,
        alerting_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> AlertIncident: ...

    def update_incident_observation(
        self,
        incident_id: int,
        *,
        observed_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> None: ...

    def recover_incident(
        self,
        incident_id: int,
        *,
        recovered_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> AlertIncident: ...

    def append_transition(
        self,
        *,
        incident_id: int | None,
        device_id: str,
        alert_type: AlertType,
        from_state: AlertLifecycleState,
        to_state: AlertLifecycleState,
        transitioned_at: datetime,
        evidence_category: str,
        evidence_message: str,
    ) -> AlertTransition: ...

    def enqueue_notification(self, notification: OperationalNotification) -> None: ...


class AlertQueryRepository(Protocol):
    def __enter__(self) -> AlertQueryRepository: ...

    def __exit__(self, *args: object) -> None: ...

    def states(self, device_id: str) -> list[AlertState]: ...

    def incidents(
        self,
        device_id: str,
        *,
        status: AlertIncidentStatus | None,
        limit: int,
    ) -> list[AlertIncident]: ...

    def evaluator_runtime(self) -> AlertEvaluatorRuntime | None: ...

    def latest_transition_at(self, device_id: str) -> datetime | None: ...


class AlertEvaluationRepositoryFactory(Protocol):
    def __call__(self) -> AlertEvaluationRepository: ...


class AlertQueryRepositoryFactory(Protocol):
    def __call__(self) -> AlertQueryRepository: ...
