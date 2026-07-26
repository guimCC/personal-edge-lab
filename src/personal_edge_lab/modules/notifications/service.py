"""Use cases for durable notification delivery and owner policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from personal_edge_lab.application.ports.notifications import (
    NotificationRepositoryFactory,
)
from personal_edge_lab.domain.notifications import (
    NotificationDelivery,
    NotificationOverview,
    NotificationPolicy,
)


class NotificationSendFailure(RuntimeError):
    def __init__(
        self,
        *,
        category: str,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.safe_message = message
        self.retry_after_seconds = retry_after_seconds


class NotificationSender(Protocol):
    def send(self, delivery: NotificationDelivery) -> str | None: ...


@dataclass(frozen=True, slots=True)
class NotificationDrainResult:
    claimed_count: int
    delivered_count: int
    failed_count: int
    expired_count: int


class DrainNotificationOutbox:
    def __init__(
        self,
        repository_factory: NotificationRepositoryFactory,
        *,
        sender: NotificationSender,
        batch_size: int,
        lease_seconds: float,
        max_age_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if batch_size <= 0 or lease_seconds <= 0 or max_age_seconds <= 0:
            raise ValueError("notification delivery settings must be positive")
        self._repository_factory = repository_factory
        self._sender = sender
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    def execute(self) -> NotificationDrainResult:
        started_at = _utc(self._clock())
        deliveries: list[NotificationDelivery] = []
        delivered_count = 0
        failed_count = 0
        expired_count = 0
        try:
            with self._repository_factory() as repository:
                repository.record_runtime_started(started_at)
                deliveries = repository.claim_due(
                    now=started_at,
                    limit=self._batch_size,
                    lease_seconds=self._lease_seconds,
                    max_age_seconds=self._max_age_seconds,
                )
            for delivery in deliveries:
                attempted_at = _utc(self._clock())
                age_seconds = max(0.0, (attempted_at - delivery.occurred_at).total_seconds())
                if age_seconds >= self._max_age_seconds:
                    with self._repository_factory() as repository:
                        repository.mark_expired(
                            delivery.id,
                            expired_at=attempted_at,
                            category="max_age_exceeded",
                        )
                    expired_count += 1
                    continue
                try:
                    external_message_id = self._sender.send(delivery)
                except NotificationSendFailure as error:
                    failed_count += 1
                    delay_seconds = _retry_delay(
                        delivery.attempt_count,
                        retry_after_seconds=error.retry_after_seconds,
                    )
                    next_attempt_at = attempted_at + timedelta(seconds=delay_seconds)
                    with self._repository_factory() as repository:
                        if (
                            next_attempt_at - delivery.occurred_at
                        ).total_seconds() >= self._max_age_seconds:
                            repository.mark_expired(
                                delivery.id,
                                expired_at=attempted_at,
                                category="max_age_exceeded",
                            )
                            expired_count += 1
                        else:
                            repository.mark_failed(
                                delivery.id,
                                attempted_at=attempted_at,
                                next_attempt_at=next_attempt_at,
                                category=error.category,
                                message=error.safe_message,
                            )
                    continue
                with self._repository_factory() as repository:
                    repository.mark_delivered(
                        delivery.id,
                        delivered_at=attempted_at,
                        external_message_id=external_message_id,
                    )
                delivered_count += 1
            finished_at = _utc(self._clock())
            with self._repository_factory() as repository:
                repository.record_runtime_success(
                    finished_at,
                    delivered_count=delivered_count,
                    failed_count=failed_count,
                )
        except BaseException:
            finished_at = _safe_now(self._clock, started_at)
            try:
                with self._repository_factory() as repository:
                    repository.record_runtime_failure(
                        finished_at,
                        category="delivery_runtime_failure",
                        message="Notification delivery cycle failed",
                    )
            except BaseException:
                pass
            raise
        return NotificationDrainResult(
            claimed_count=len(deliveries),
            delivered_count=delivered_count,
            failed_count=failed_count,
            expired_count=expired_count,
        )


class ManageNotificationPolicy:
    def __init__(
        self,
        repository_factory: NotificationRepositoryFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository_factory = repository_factory
        self._clock = clock

    def get(self) -> NotificationOverview:
        now = _utc(self._clock())
        with self._repository_factory() as repository:
            return repository.overview(now=now)

    def pause_for(self, duration: timedelta) -> NotificationPolicy:
        if duration.total_seconds() <= 0:
            raise ValueError("notification pause duration must be positive")
        now = _utc(self._clock())
        with self._repository_factory() as repository:
            return repository.pause_until(until=now + duration, changed_at=now)

    def pause_until(self, until: datetime) -> NotificationPolicy:
        now = _utc(self._clock())
        with self._repository_factory() as repository:
            return repository.pause_until(until=_utc(until), changed_at=now)

    def pause_indefinitely(self) -> NotificationPolicy:
        now = _utc(self._clock())
        with self._repository_factory() as repository:
            return repository.pause_indefinitely(changed_at=now)

    def resume(self) -> NotificationPolicy:
        now = _utc(self._clock())
        with self._repository_factory() as repository:
            return repository.resume(changed_at=now)


def _retry_delay(attempt_count: int, *, retry_after_seconds: float | None) -> float:
    schedule = (30.0, 120.0, 600.0, 1800.0, 3600.0)
    selected = schedule[min(max(attempt_count - 1, 0), len(schedule) - 1)]
    if retry_after_seconds is not None:
        selected = max(selected, retry_after_seconds)
    return selected


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("notification clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _safe_now(clock: Callable[[], datetime], fallback: datetime) -> datetime:
    try:
        return _utc(clock())
    except BaseException:
        return fallback
