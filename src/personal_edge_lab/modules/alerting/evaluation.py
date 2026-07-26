"""Deterministic operational alert evaluation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from personal_edge_lab.application.ports.alerting import (
    AlertEvaluationRepository,
    AlertEvaluationRepositoryFactory,
)
from personal_edge_lab.domain.alerting import (
    AlertEvaluationResult,
    AlertIncident,
    AlertLifecycleState,
    AlertPolicy,
    AlertSignal,
    AlertSignalStatus,
    AlertState,
    AlertTransition,
    AlertType,
)
from personal_edge_lab.domain.notifications import (
    NotificationEventType,
    OperationalNotification,
)
from personal_edge_lab.domain.telemetry import (
    CollectionAttemptOutcome,
    CollectorRuntimeStatus,
    TemperatureReading,
)

LOGGER = logging.getLogger(__name__)


class AlertEvaluationError(ValueError):
    """Raised when alert evaluation configuration or clock values are invalid."""


class EvaluateOperationalAlerts:
    def __init__(
        self,
        repository_factory: AlertEvaluationRepositoryFactory,
        *,
        device_id: str,
        policy: AlertPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository_factory = repository_factory
        self._device_id = _device_id(device_id)
        self._policy = policy
        self._clock = clock

    def execute(self) -> AlertEvaluationResult:
        started_at = _utc_time(self._clock())
        with self._repository_factory() as repository:
            repository.record_evaluator_started(started_at)

        try:
            result = self._evaluate(started_at)
        except BaseException:
            finished_at = _safe_now(self._clock, started_at)
            try:
                with self._repository_factory() as repository:
                    repository.record_evaluator_failure(
                        finished_at,
                        category="evaluation_failure",
                        message="operational alert evaluation failed",
                    )
            except BaseException:
                LOGGER.exception("Unable to record alert evaluator failure")
            raise
        for transition in result.transitions:
            LOGGER.info(
                "Alert transition device=%s type=%s from=%s to=%s incident_id=%s",
                transition.device_id,
                transition.alert_type,
                transition.from_state,
                transition.to_state,
                transition.incident_id,
            )
        return result

    def _evaluate(self, evaluated_at: datetime) -> AlertEvaluationResult:
        with self._repository_factory() as repository:
            repository.begin_evaluation()
            try:
                reading = repository.latest_temperature(self._device_id)
                collector = repository.collector_status(self._device_id)
                signals = {
                    AlertType.TELEMETRY_STALE: self._telemetry_signal(
                        reading,
                        evaluated_at,
                        repository.get_state(
                            self._device_id,
                            AlertType.TELEMETRY_STALE,
                        ),
                    ),
                    AlertType.EDGE_UNAVAILABLE: self._edge_signal(
                        collector,
                        evaluated_at,
                        repository.get_state(
                            self._device_id,
                            AlertType.EDGE_UNAVAILABLE,
                        ),
                    ),
                }
                states: list[AlertState] = []
                transitions: list[AlertTransition] = []
                for alert_type in AlertType:
                    state = repository.get_state(self._device_id, alert_type)
                    if state is None:
                        state = _healthy_state(
                            self._device_id,
                            alert_type,
                            evaluated_at,
                            signals[alert_type],
                        )
                    state, transition = self._transition(
                        repository,
                        state,
                        signals[alert_type],
                        reading=reading,
                        collector=collector,
                        evaluated_at=evaluated_at,
                    )
                    repository.save_state(state)
                    states.append(state)
                    if transition is not None:
                        transitions.append(transition)
                        notification = _notification_for_transition(repository, transition)
                        if notification is not None:
                            repository.enqueue_notification(notification)
                repository.record_evaluator_success(evaluated_at)
                repository.commit()
            except BaseException:
                repository.rollback()
                raise
        return AlertEvaluationResult(
            device_id=self._device_id,
            evaluated_at=evaluated_at,
            states=tuple(states),
            transitions=tuple(transitions),
        )

    def _telemetry_signal(
        self,
        reading: TemperatureReading | None,
        evaluated_at: datetime,
        state: AlertState | None,
    ) -> AlertSignal:
        if reading is None:
            suspect_at = None if state is None else state.suspect_started_at
            alert_ready = (
                suspect_at is not None
                and (evaluated_at - suspect_at).total_seconds()
                >= self._policy.telemetry_alert_after_seconds
            )
            return AlertSignal(
                status=AlertSignalStatus.BAD,
                alert_ready=alert_ready,
                evidence_category="no_data",
                evidence_message="No telemetry has been stored for the device",
            )
        age_seconds = max(0.0, (evaluated_at - reading.received_at).total_seconds())
        if age_seconds <= self._policy.telemetry_suspect_after_seconds:
            return AlertSignal(
                status=AlertSignalStatus.GOOD,
                alert_ready=False,
                evidence_category="fresh",
                evidence_message="Fresh telemetry is available",
            )
        return AlertSignal(
            status=AlertSignalStatus.BAD,
            alert_ready=age_seconds > self._policy.telemetry_alert_after_seconds,
            evidence_category="stale",
            evidence_message="Telemetry has remained stale",
        )

    def _edge_signal(
        self,
        collector: CollectorRuntimeStatus | None,
        evaluated_at: datetime,
        state: AlertState | None,
    ) -> AlertSignal:
        if collector is None or collector.stopped_at is not None:
            return _unknown_edge_signal()
        heartbeat_age = max(0.0, (evaluated_at - collector.heartbeat_at).total_seconds())
        if heartbeat_age > self._policy.telemetry_suspect_after_seconds:
            return _unknown_edge_signal()
        if collector.last_attempt_outcome is CollectionAttemptOutcome.SUCCESS:
            return AlertSignal(
                status=AlertSignalStatus.GOOD,
                alert_ready=False,
                evidence_category="reachable",
                evidence_message="The latest collection attempt succeeded",
            )
        if collector.last_attempt_outcome is not CollectionAttemptOutcome.FAILURE:
            return _unknown_edge_signal()
        suspect_at = None if state is None else state.suspect_started_at
        sustained = (
            suspect_at is not None
            and (evaluated_at - suspect_at).total_seconds() >= self._policy.edge_alert_after_seconds
        )
        return AlertSignal(
            status=AlertSignalStatus.BAD,
            alert_ready=(
                collector.consecutive_failures >= self._policy.edge_min_consecutive_failures
                and sustained
            ),
            evidence_category=collector.last_failure_category or "collection_failure",
            evidence_message=_safe_message(
                collector.last_failure_message,
                fallback="Repeated temperature collection attempts failed",
            ),
        )

    def _transition(
        self,
        repository: AlertEvaluationRepository,
        state: AlertState,
        signal: AlertSignal,
        *,
        reading: TemperatureReading | None,
        collector: CollectorRuntimeStatus | None,
        evaluated_at: datetime,
    ) -> tuple[AlertState, AlertTransition | None]:
        if state.lifecycle is AlertLifecycleState.HEALTHY:
            if signal.status is AlertSignalStatus.BAD:
                updated = replace(
                    state,
                    lifecycle=AlertLifecycleState.SUSPECT,
                    suspect_started_at=evaluated_at,
                    recovered_at=None,
                    recovery_display_until=None,
                    last_observed_at=evaluated_at,
                    evidence_category=signal.evidence_category,
                    evidence_message=signal.evidence_message,
                )
                return updated, _append_transition(repository, state, updated, evaluated_at)
            return _observe(state, signal, evaluated_at), None

        if state.lifecycle is AlertLifecycleState.SUSPECT:
            if signal.status is AlertSignalStatus.GOOD:
                updated = _healthy_state(
                    state.device_id,
                    state.alert_type,
                    evaluated_at,
                    signal,
                )
                return updated, _append_transition(repository, state, updated, evaluated_at)
            if signal.status is AlertSignalStatus.BAD and signal.alert_ready:
                suspect_started_at = state.suspect_started_at or evaluated_at
                incident = repository.create_incident(
                    device_id=state.device_id,
                    alert_type=state.alert_type,
                    suspect_started_at=suspect_started_at,
                    alerting_at=evaluated_at,
                    evidence_category=signal.evidence_category,
                    evidence_message=signal.evidence_message,
                )
                updated = replace(
                    state,
                    lifecycle=AlertLifecycleState.ALERTING,
                    active_incident_id=incident.id,
                    last_observed_at=evaluated_at,
                    evidence_category=signal.evidence_category,
                    evidence_message=signal.evidence_message,
                )
                return updated, _append_transition(
                    repository,
                    state,
                    updated,
                    evaluated_at,
                    incident_id=incident.id,
                )
            return _observe(state, signal, evaluated_at), None

        if state.lifecycle is AlertLifecycleState.ALERTING:
            incident = (
                None
                if state.active_incident_id is None
                else repository.get_incident(state.active_incident_id)
            )
            if incident is None:
                raise RuntimeError("alerting state has no active incident")
            if signal.status is AlertSignalStatus.GOOD and self._can_recover(
                state.alert_type,
                incident,
                reading,
                collector,
            ):
                repository.recover_incident(
                    incident.id,
                    recovered_at=evaluated_at,
                    evidence_category=signal.evidence_category,
                    evidence_message=signal.evidence_message,
                )
                updated = replace(
                    state,
                    lifecycle=AlertLifecycleState.RECOVERED,
                    active_incident_id=None,
                    recovered_at=evaluated_at,
                    recovery_display_until=evaluated_at
                    + timedelta(seconds=self._policy.recovery_display_seconds),
                    last_observed_at=evaluated_at,
                    evidence_category=signal.evidence_category,
                    evidence_message=signal.evidence_message,
                )
                return updated, _append_transition(
                    repository,
                    state,
                    updated,
                    evaluated_at,
                    incident_id=incident.id,
                )
            repository.update_incident_observation(
                incident.id,
                observed_at=evaluated_at,
                evidence_category=signal.evidence_category,
                evidence_message=signal.evidence_message,
            )
            return _observe(state, signal, evaluated_at), None

        if signal.status is AlertSignalStatus.BAD:
            updated = replace(
                state,
                lifecycle=AlertLifecycleState.SUSPECT,
                suspect_started_at=evaluated_at,
                active_incident_id=None,
                recovered_at=None,
                recovery_display_until=None,
                last_observed_at=evaluated_at,
                evidence_category=signal.evidence_category,
                evidence_message=signal.evidence_message,
            )
            return updated, _append_transition(repository, state, updated, evaluated_at)
        if (
            state.recovery_display_until is not None
            and evaluated_at >= state.recovery_display_until
        ):
            updated = _healthy_state(
                state.device_id,
                state.alert_type,
                evaluated_at,
                signal,
            )
            return updated, _append_transition(repository, state, updated, evaluated_at)
        return _observe(state, signal, evaluated_at), None

    @staticmethod
    def _can_recover(
        alert_type: AlertType,
        incident: AlertIncident,
        reading: TemperatureReading | None,
        collector: CollectorRuntimeStatus | None,
    ) -> bool:
        if alert_type is AlertType.TELEMETRY_STALE:
            return reading is not None and reading.received_at > incident.alerting_at
        return (
            collector is not None
            and collector.last_attempt_outcome is CollectionAttemptOutcome.SUCCESS
            and collector.last_success_at is not None
            and collector.last_success_at > incident.alerting_at
        )


def _healthy_state(
    device_id: str,
    alert_type: AlertType,
    observed_at: datetime,
    signal: AlertSignal,
) -> AlertState:
    return AlertState(
        device_id=device_id,
        alert_type=alert_type,
        lifecycle=AlertLifecycleState.HEALTHY,
        suspect_started_at=None,
        active_incident_id=None,
        recovered_at=None,
        recovery_display_until=None,
        last_observed_at=observed_at,
        evidence_category=signal.evidence_category,
        evidence_message=signal.evidence_message,
    )


def _observe(state: AlertState, signal: AlertSignal, observed_at: datetime) -> AlertState:
    return replace(
        state,
        last_observed_at=observed_at,
        evidence_category=signal.evidence_category,
        evidence_message=signal.evidence_message,
    )


def _append_transition(
    repository: AlertEvaluationRepository,
    previous: AlertState,
    current: AlertState,
    transitioned_at: datetime,
    *,
    incident_id: int | None = None,
) -> AlertTransition:
    return repository.append_transition(
        incident_id=incident_id,
        device_id=current.device_id,
        alert_type=current.alert_type,
        from_state=previous.lifecycle,
        to_state=current.lifecycle,
        transitioned_at=transitioned_at,
        evidence_category=current.evidence_category,
        evidence_message=current.evidence_message,
    )


def _notification_for_transition(
    repository: AlertEvaluationRepository,
    transition: AlertTransition,
) -> OperationalNotification | None:
    event_type: NotificationEventType
    if transition.to_state is AlertLifecycleState.ALERTING:
        event_type = NotificationEventType.OPERATIONAL_ALERT_STARTED
    elif transition.to_state is AlertLifecycleState.RECOVERED:
        event_type = NotificationEventType.OPERATIONAL_ALERT_RECOVERED
    else:
        return None
    if transition.incident_id is None:
        raise RuntimeError("notifiable alert transition has no incident")
    incident = repository.get_incident(transition.incident_id)
    if incident is None:
        raise RuntimeError("notifiable alert transition has no stored incident")
    return OperationalNotification(
        transition_id=transition.id,
        incident_id=incident.id,
        device_id=transition.device_id,
        alert_type=transition.alert_type,
        event_type=event_type,
        occurred_at=transition.transitioned_at,
        suspect_started_at=incident.suspect_started_at,
        alerting_at=incident.alerting_at,
        recovered_at=incident.recovered_at,
        evidence_category=transition.evidence_category,
    )


def _unknown_edge_signal() -> AlertSignal:
    return AlertSignal(
        status=AlertSignalStatus.UNKNOWN,
        alert_ready=False,
        evidence_category="unknown",
        evidence_message="Collector evidence is unavailable or stale",
    )


def _safe_message(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    collapsed = " ".join(value.split())
    return (collapsed or fallback)[:240]


def _safe_now(clock: Callable[[], datetime], fallback: datetime) -> datetime:
    try:
        return _utc_time(clock())
    except BaseException:
        return fallback


def _utc_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertEvaluationError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _device_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AlertEvaluationError("device_id must not be empty")
    return normalized
