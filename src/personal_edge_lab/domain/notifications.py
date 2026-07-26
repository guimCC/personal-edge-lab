"""Durable outbound-notification domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from personal_edge_lab.domain.alerting import AlertType


class NotificationEventType(StrEnum):
    OPERATIONAL_ALERT_STARTED = "operational_alert_started"
    OPERATIONAL_ALERT_RECOVERED = "operational_alert_recovered"


class NotificationDeliveryStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    DELIVERED = "delivered"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"


class NotificationPolicyMode(StrEnum):
    ENABLED = "enabled"
    PAUSED_UNTIL = "paused_until"
    PAUSED_INDEFINITELY = "paused_indefinitely"


class NotificationRuntimeOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class OperationalNotification:
    transition_id: int
    incident_id: int
    device_id: str
    alert_type: AlertType
    event_type: NotificationEventType
    occurred_at: datetime
    suspect_started_at: datetime
    alerting_at: datetime
    recovered_at: datetime | None
    evidence_category: str


@dataclass(frozen=True, slots=True)
class NotificationDelivery:
    id: int
    event_type: NotificationEventType
    device_id: str
    alert_type: AlertType
    incident_id: int
    transition_id: int
    occurred_at: datetime
    payload: dict[str, Any]
    attempt_count: int
    coalesced_count: int


@dataclass(frozen=True, slots=True)
class NotificationPolicy:
    mode: NotificationPolicyMode
    paused_until: datetime | None
    changed_at: datetime | None

    def is_paused(self, at: datetime) -> bool:
        if self.mode is NotificationPolicyMode.PAUSED_INDEFINITELY:
            return True
        return (
            self.mode is NotificationPolicyMode.PAUSED_UNTIL
            and self.paused_until is not None
            and at < self.paused_until
        )


@dataclass(frozen=True, slots=True)
class NotificationDeliveryRuntime:
    last_started_at: datetime
    last_finished_at: datetime | None
    last_outcome: NotificationRuntimeOutcome | None
    delivered_count: int
    failed_count: int
    last_error_category: str | None
    last_error_message: str | None


@dataclass(frozen=True, slots=True)
class NotificationOverview:
    policy: NotificationPolicy
    pending_count: int
    failed_pending_count: int
    oldest_pending_at: datetime | None
    runtime: NotificationDeliveryRuntime | None
