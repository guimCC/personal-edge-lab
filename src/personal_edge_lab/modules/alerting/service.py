"""Deterministic operational alert evaluation and read use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from personal_edge_lab.application.ports.alerting import AlertRepository, AlertRepositoryFactory
from personal_edge_lab.domain.alerting import (
    AlertEvaluationResult,
    AlertEvaluatorRuntime,
    AlertIncident,
    AlertIncidentStatus,
    AlertLifecycleState,
    AlertPolicy,
    AlertSignal,
    AlertSignalStatus,
    AlertState,
    AlertTransition,
    AlertType,
)
from personal_edge_lab.domain.telemetry import (
    CollectionAttemptOutcome,
    CollectorRuntimeStatus,
    TemperatureReading,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_ALERT_LIMIT = 20
MAX_ALERT_LIMIT = 100


class AlertQueryError(ValueError):
    """Raised when an alert query or clock value is invalid."""


class AlertHistoryFilter(StrEnum):
    ACTIVE = "active"
    RECOVERED = "recovered"
    ALL = "all"


class AlertStatusSummary(StrEnum):
    HEALTHY = "healthy"
    SUSPECT = "suspect"
    ALERTING = "alerting"
    RECOVERED = "recovered"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AlertOverview:
    device_id: str
    status: AlertStatusSummary
    active_count: int
    suspect_count: int
    latest_transition_at: datetime | None
    evaluator_last_run_at: datetime | None
    evaluator_age_seconds: float | None
    states: tuple[AlertState, ...]
    incidents: tuple[AlertIncident, ...]
    limit: int


class EvaluateOperationalAlerts:
    def __init__(
        self,
        repository_factory: AlertRepositoryFactory,
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
                observed_at=evaluated_at,
                alert_ready=alert_ready,
                evidence_category="no_data",
                evidence_message="No telemetry has been stored for the device",
            )
        age_seconds = max(0.0, (evaluated_at - reading.received_at).total_seconds())
        if age_seconds <= self._policy.telemetry_suspect_after_seconds:
            return AlertSignal(
                status=AlertSignalStatus.GOOD,
                observed_at=evaluated_at,
                alert_ready=False,
                evidence_category="fresh",
                evidence_message="Fresh telemetry is available",
            )
        return AlertSignal(
            status=AlertSignalStatus.BAD,
            observed_at=evaluated_at,
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
            return _unknown_edge_signal(evaluated_at)
        heartbeat_age = max(0.0, (evaluated_at - collector.heartbeat_at).total_seconds())
        if heartbeat_age > self._policy.telemetry_suspect_after_seconds:
            return _unknown_edge_signal(evaluated_at)
        if collector.last_attempt_outcome is CollectionAttemptOutcome.SUCCESS:
            return AlertSignal(
                status=AlertSignalStatus.GOOD,
                observed_at=evaluated_at,
                alert_ready=False,
                evidence_category="reachable",
                evidence_message="The latest collection attempt succeeded",
            )
        if collector.last_attempt_outcome is not CollectionAttemptOutcome.FAILURE:
            return _unknown_edge_signal(evaluated_at)
        suspect_at = None if state is None else state.suspect_started_at
        sustained = (
            suspect_at is not None
            and (evaluated_at - suspect_at).total_seconds() >= self._policy.edge_alert_after_seconds
        )
        return AlertSignal(
            status=AlertSignalStatus.BAD,
            observed_at=evaluated_at,
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
        repository: AlertRepository,
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


class GetOperationalAlerts:
    def __init__(
        self,
        repository_factory: AlertRepositoryFactory,
        *,
        evaluator_stale_after_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if evaluator_stale_after_seconds <= 0:
            raise AlertQueryError("evaluator stale threshold must be greater than zero")
        self._repository_factory = repository_factory
        self._evaluator_stale_after_seconds = evaluator_stale_after_seconds
        self._clock = clock

    def execute(
        self,
        device_id: str,
        *,
        history_filter: AlertHistoryFilter = AlertHistoryFilter.ALL,
        limit: int = DEFAULT_ALERT_LIMIT,
    ) -> AlertOverview:
        selected_device = _device_id(device_id)
        if not 1 <= limit <= MAX_ALERT_LIMIT:
            raise AlertQueryError(f"limit must be from 1 through {MAX_ALERT_LIMIT}")
        checked_at = _utc_time(self._clock())
        incident_status = {
            AlertHistoryFilter.ACTIVE: AlertIncidentStatus.ACTIVE,
            AlertHistoryFilter.RECOVERED: AlertIncidentStatus.RECOVERED,
            AlertHistoryFilter.ALL: None,
        }[history_filter]
        with self._repository_factory() as repository:
            states = tuple(repository.states(selected_device))
            incidents = tuple(
                repository.incidents(
                    selected_device,
                    status=incident_status,
                    limit=limit,
                )
            )
            runtime = repository.evaluator_runtime()
            latest_transition = repository.latest_transition_at(selected_device)
        evaluator_last_run, evaluator_age = _evaluator_age(runtime, checked_at)
        status = _overview_status(
            states,
            runtime,
            evaluator_age,
            stale_after_seconds=self._evaluator_stale_after_seconds,
        )
        return AlertOverview(
            device_id=selected_device,
            status=status,
            active_count=sum(state.lifecycle is AlertLifecycleState.ALERTING for state in states),
            suspect_count=sum(state.lifecycle is AlertLifecycleState.SUSPECT for state in states),
            latest_transition_at=latest_transition,
            evaluator_last_run_at=evaluator_last_run,
            evaluator_age_seconds=evaluator_age,
            states=states,
            incidents=incidents,
            limit=limit,
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
    repository: AlertRepository,
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


def _unknown_edge_signal(observed_at: datetime) -> AlertSignal:
    return AlertSignal(
        status=AlertSignalStatus.UNKNOWN,
        observed_at=observed_at,
        alert_ready=False,
        evidence_category="unknown",
        evidence_message="Collector evidence is unavailable or stale",
    )


def _safe_message(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    collapsed = " ".join(value.split())
    return (collapsed or fallback)[:240]


def _overview_status(
    states: tuple[AlertState, ...],
    runtime: AlertEvaluatorRuntime | None,
    evaluator_age_seconds: float | None,
    *,
    stale_after_seconds: float,
) -> AlertStatusSummary:
    if (
        runtime is None
        or runtime.last_outcome is None
        or runtime.last_outcome.value != "success"
        or evaluator_age_seconds is None
        or evaluator_age_seconds > stale_after_seconds
    ):
        return AlertStatusSummary.UNKNOWN
    lifecycles = {state.lifecycle for state in states}
    if AlertLifecycleState.ALERTING in lifecycles:
        return AlertStatusSummary.ALERTING
    if AlertLifecycleState.SUSPECT in lifecycles:
        return AlertStatusSummary.SUSPECT
    if AlertLifecycleState.RECOVERED in lifecycles:
        return AlertStatusSummary.RECOVERED
    return AlertStatusSummary.HEALTHY


def _evaluator_age(
    runtime: AlertEvaluatorRuntime | None,
    checked_at: datetime,
) -> tuple[datetime | None, float | None]:
    if runtime is None or runtime.last_finished_at is None:
        return None, None
    return (
        runtime.last_finished_at,
        max(0.0, (checked_at - runtime.last_finished_at).total_seconds()),
    )


def _safe_now(clock: Callable[[], datetime], fallback: datetime) -> datetime:
    try:
        return _utc_time(clock())
    except BaseException:
        return fallback


def _utc_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertQueryError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _device_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AlertQueryError("device_id must not be empty")
    return normalized
