"""Persistence and delivery ports for outbound notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from personal_edge_lab.domain.notifications import (
    NotificationDelivery,
    NotificationOverview,
    NotificationPolicy,
)


class NotificationRepository(Protocol):
    def __enter__(self) -> NotificationRepository: ...

    def __exit__(self, *args: object) -> None: ...

    def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_seconds: float,
        max_age_seconds: float,
    ) -> list[NotificationDelivery]: ...

    def mark_delivered(
        self,
        delivery_id: int,
        *,
        delivered_at: datetime,
        external_message_id: str | None,
    ) -> None: ...

    def mark_failed(
        self,
        delivery_id: int,
        *,
        attempted_at: datetime,
        next_attempt_at: datetime,
        category: str,
        message: str,
    ) -> None: ...

    def mark_expired(
        self,
        delivery_id: int,
        *,
        expired_at: datetime,
        category: str,
    ) -> None: ...

    def record_runtime_started(self, started_at: datetime) -> None: ...

    def record_runtime_success(
        self,
        finished_at: datetime,
        *,
        delivered_count: int,
        failed_count: int,
    ) -> None: ...

    def record_runtime_failure(
        self,
        finished_at: datetime,
        *,
        category: str,
        message: str,
    ) -> None: ...

    def policy(self, *, now: datetime) -> NotificationPolicy: ...

    def pause_until(self, *, until: datetime, changed_at: datetime) -> NotificationPolicy: ...

    def pause_indefinitely(self, *, changed_at: datetime) -> NotificationPolicy: ...

    def resume(self, *, changed_at: datetime) -> NotificationPolicy: ...

    def overview(self, *, now: datetime) -> NotificationOverview: ...


class NotificationRepositoryFactory(Protocol):
    def __call__(self) -> NotificationRepository: ...
