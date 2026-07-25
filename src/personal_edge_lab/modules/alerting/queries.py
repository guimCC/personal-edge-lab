"""Read-only operational alert queries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from personal_edge_lab.application.ports.alerting import (
    AlertQueryRepository,
    AlertQueryRepositoryFactory,
)
from personal_edge_lab.domain.alerting import (
    AlertEvaluatorRuntime,
    AlertIncident,
    AlertIncidentStatus,
    AlertLifecycleState,
    AlertState,
)

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


class GetOperationalAlerts:
    def __init__(
        self,
        repository_factory: AlertQueryRepositoryFactory,
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
        with self._repository_factory() as repository:
            states = tuple(repository.states(selected_device))
            incidents = self._incidents(repository, selected_device, history_filter, limit)
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

    @staticmethod
    def _incidents(
        repository: AlertQueryRepository,
        device_id: str,
        history_filter: AlertHistoryFilter,
        limit: int,
    ) -> tuple[AlertIncident, ...]:
        if history_filter is AlertHistoryFilter.ALL:
            active = repository.incidents(
                device_id,
                status=AlertIncidentStatus.ACTIVE,
                limit=limit,
            )
            recovered = repository.incidents(
                device_id,
                status=AlertIncidentStatus.RECOVERED,
                limit=limit,
            )
            return tuple(
                sorted(
                    (*active, *recovered),
                    key=lambda item: item.id,
                    reverse=True,
                )
            )
        status = (
            AlertIncidentStatus.ACTIVE
            if history_filter is AlertHistoryFilter.ACTIVE
            else AlertIncidentStatus.RECOVERED
        )
        return tuple(repository.incidents(device_id, status=status, limit=limit))


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


def _utc_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertQueryError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _device_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AlertQueryError("device_id must not be empty")
    return normalized
