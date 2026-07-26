"""SQLite outbox, delivery runtime, and owner notification policy."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from personal_edge_lab.domain.alerting import AlertType
from personal_edge_lab.domain.notifications import (
    NotificationDelivery,
    NotificationDeliveryRuntime,
    NotificationEventType,
    NotificationOverview,
    NotificationPolicy,
    NotificationPolicyMode,
    NotificationRuntimeOutcome,
)
from personal_edge_lab.infrastructure.persistence.sqlite.connection import open_connection

CHANNEL = "telegram"
RECIPIENT = "owner"
TOPIC = "operational_alerts"


class SqliteNotificationRepository:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._connection = open_connection(database_path, timeout_seconds=timeout_seconds)

    def __enter__(self) -> SqliteNotificationRepository:
        return self

    def __exit__(self, *args: object) -> None:
        if self._connection.in_transaction:
            self._connection.rollback()
        self._connection.close()

    def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_seconds: float,
        max_age_seconds: float,
    ) -> list[NotificationDelivery]:
        if limit <= 0 or lease_seconds <= 0 or max_age_seconds <= 0:
            raise ValueError("notification delivery bounds must be positive")
        lease_until = now + timedelta(seconds=lease_seconds)
        expiry_boundary = now - timedelta(seconds=max_age_seconds)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'expired',
                    leased_until_utc = NULL,
                    last_error_category = 'max_age_exceeded',
                    last_error_message = 'Notification expired before delivery'
                WHERE status IN ('pending', 'leased')
                  AND occurred_at_utc <= ?
                """,
                (expiry_boundary.isoformat(),),
            )
            self._connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'pending',
                    leased_until_utc = NULL,
                    last_error_category = 'lease_recovered',
                    last_error_message = 'Expired delivery lease was recovered'
                WHERE status = 'leased'
                  AND leased_until_utc <= ?
                """,
                (now.isoformat(),),
            )
            rows = self._connection.execute(
                """
                SELECT id
                FROM notification_outbox
                WHERE channel = ?
                  AND recipient = ?
                  AND topic = ?
                  AND status = 'pending'
                  AND next_attempt_at_utc <= ?
                ORDER BY next_attempt_at_utc ASC, id ASC
                LIMIT ?
                """,
                (CHANNEL, RECIPIENT, TOPIC, now.isoformat(), limit),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            for delivery_id in ids:
                self._connection.execute(
                    """
                    UPDATE notification_outbox
                    SET status = 'leased',
                        attempt_count = attempt_count + 1,
                        leased_until_utc = ?,
                        last_attempt_at_utc = ?,
                        last_error_category = NULL,
                        last_error_message = NULL
                    WHERE id = ? AND status = 'pending'
                    """,
                    (lease_until.isoformat(), now.isoformat(), delivery_id),
                )
            deliveries = [self._delivery(delivery_id) for delivery_id in ids]
            self._connection.commit()
            return deliveries
        except BaseException:
            self._connection.rollback()
            raise

    def mark_delivered(
        self,
        delivery_id: int,
        *,
        delivered_at: datetime,
        external_message_id: str | None,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'delivered',
                delivered_at_utc = ?,
                external_message_id = ?,
                leased_until_utc = NULL,
                last_error_category = NULL,
                last_error_message = NULL
            WHERE id = ? AND status = 'leased'
            """,
            (delivered_at.isoformat(), external_message_id, delivery_id),
        )
        _require_row(cursor, "leased notification was not found")
        self._connection.commit()

    def mark_failed(
        self,
        delivery_id: int,
        *,
        attempted_at: datetime,
        next_attempt_at: datetime,
        category: str,
        message: str,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'pending',
                next_attempt_at_utc = ?,
                leased_until_utc = NULL,
                last_attempt_at_utc = ?,
                last_error_category = ?,
                last_error_message = ?
            WHERE id = ? AND status = 'leased'
            """,
            (
                next_attempt_at.isoformat(),
                attempted_at.isoformat(),
                _safe_text(category, fallback="delivery_failure", limit=64),
                _safe_text(message, fallback="Notification delivery failed", limit=240),
                delivery_id,
            ),
        )
        _require_row(cursor, "leased notification was not found")
        self._connection.commit()

    def mark_expired(
        self,
        delivery_id: int,
        *,
        expired_at: datetime,
        category: str,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'expired',
                leased_until_utc = NULL,
                last_attempt_at_utc = ?,
                last_error_category = ?,
                last_error_message = 'Notification expired before delivery'
            WHERE id = ? AND status IN ('pending', 'leased')
            """,
            (
                expired_at.isoformat(),
                _safe_text(category, fallback="max_age_exceeded", limit=64),
                delivery_id,
            ),
        )
        _require_row(cursor, "active notification was not found")
        self._connection.commit()

    def record_runtime_started(self, started_at: datetime) -> None:
        self._connection.execute(
            """
            INSERT INTO notification_delivery_runtime (
                singleton_id, last_started_at_utc, last_finished_at_utc,
                last_outcome, delivered_count, failed_count,
                last_error_category, last_error_message
            ) VALUES (1, ?, NULL, NULL, 0, 0, NULL, NULL)
            ON CONFLICT(singleton_id) DO UPDATE SET
                last_started_at_utc = excluded.last_started_at_utc,
                last_outcome = NULL,
                delivered_count = 0,
                failed_count = 0,
                last_error_category = NULL,
                last_error_message = NULL
            """,
            (started_at.isoformat(),),
        )
        self._connection.commit()

    def record_runtime_success(
        self,
        finished_at: datetime,
        *,
        delivered_count: int,
        failed_count: int,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE notification_delivery_runtime
            SET last_finished_at_utc = ?,
                last_outcome = 'success',
                delivered_count = ?,
                failed_count = ?,
                last_error_category = NULL,
                last_error_message = NULL
            WHERE singleton_id = 1
            """,
            (finished_at.isoformat(), delivered_count, failed_count),
        )
        _require_row(cursor, "notification runtime was not initialized")
        self._connection.commit()

    def record_runtime_failure(
        self,
        finished_at: datetime,
        *,
        category: str,
        message: str,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE notification_delivery_runtime
            SET last_finished_at_utc = ?,
                last_outcome = 'failure',
                last_error_category = ?,
                last_error_message = ?
            WHERE singleton_id = 1
            """,
            (
                finished_at.isoformat(),
                _safe_text(category, fallback="delivery_failure", limit=64),
                _safe_text(message, fallback="Notification delivery failed", limit=240),
            ),
        )
        _require_row(cursor, "notification runtime was not initialized")
        self._connection.commit()

    def policy(self, *, now: datetime) -> NotificationPolicy:
        row = self._connection.execute(
            """
            SELECT mode, paused_until_utc, changed_at_utc
            FROM notification_policy
            WHERE channel = ? AND recipient = ? AND topic = ?
            """,
            (CHANNEL, RECIPIENT, TOPIC),
        ).fetchone()
        if row is None:
            return NotificationPolicy(
                mode=NotificationPolicyMode.ENABLED,
                paused_until=None,
                changed_at=None,
            )
        policy = _policy_from_row(row)
        if (
            policy.mode is NotificationPolicyMode.PAUSED_UNTIL
            and policy.paused_until is not None
            and now >= policy.paused_until
        ):
            return NotificationPolicy(
                mode=NotificationPolicyMode.ENABLED,
                paused_until=None,
                changed_at=policy.changed_at,
            )
        return policy

    def pause_until(self, *, until: datetime, changed_at: datetime) -> NotificationPolicy:
        if until <= changed_at:
            raise ValueError("notification pause must end in the future")
        return self._set_policy(
            mode=NotificationPolicyMode.PAUSED_UNTIL,
            paused_until=until,
            changed_at=changed_at,
        )

    def pause_indefinitely(self, *, changed_at: datetime) -> NotificationPolicy:
        return self._set_policy(
            mode=NotificationPolicyMode.PAUSED_INDEFINITELY,
            paused_until=None,
            changed_at=changed_at,
        )

    def resume(self, *, changed_at: datetime) -> NotificationPolicy:
        return self._set_policy(
            mode=NotificationPolicyMode.ENABLED,
            paused_until=None,
            changed_at=changed_at,
            suppress_pending=False,
        )

    def overview(self, *, now: datetime) -> NotificationOverview:
        pending = self._connection.execute(
            """
            SELECT COUNT(*) AS count,
                   COALESCE(SUM(
                       CASE
                           WHEN status = 'pending'
                            AND last_error_category IS NOT NULL
                            AND last_error_category NOT IN ('coalesced', 'lease_recovered')
                           THEN 1
                           ELSE 0
                       END
                   ), 0) AS failed_count,
                   MIN(occurred_at_utc) AS oldest
            FROM notification_outbox
            WHERE channel = ? AND recipient = ? AND topic = ?
              AND status IN ('pending', 'leased')
            """,
            (CHANNEL, RECIPIENT, TOPIC),
        ).fetchone()
        runtime_row = self._connection.execute(
            """
            SELECT last_started_at_utc, last_finished_at_utc, last_outcome,
                   delivered_count, failed_count,
                   last_error_category, last_error_message
            FROM notification_delivery_runtime
            WHERE singleton_id = 1
            """
        ).fetchone()
        return NotificationOverview(
            policy=self.policy(now=now),
            pending_count=int(pending["count"]),
            failed_pending_count=int(pending["failed_count"]),
            oldest_pending_at=_optional_datetime(pending["oldest"]),
            runtime=None if runtime_row is None else _runtime_from_row(runtime_row),
        )

    def _set_policy(
        self,
        *,
        mode: NotificationPolicyMode,
        paused_until: datetime | None,
        changed_at: datetime,
        suppress_pending: bool = True,
    ) -> NotificationPolicy:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                INSERT INTO notification_policy (
                    channel, recipient, topic, mode, paused_until_utc,
                    changed_at_utc, changed_by
                ) VALUES (?, ?, ?, ?, ?, ?, 'owner')
                ON CONFLICT(channel, recipient, topic) DO UPDATE SET
                    mode = excluded.mode,
                    paused_until_utc = excluded.paused_until_utc,
                    changed_at_utc = excluded.changed_at_utc,
                    changed_by = excluded.changed_by
                """,
                (
                    CHANNEL,
                    RECIPIENT,
                    TOPIC,
                    mode.value,
                    None if paused_until is None else paused_until.isoformat(),
                    changed_at.isoformat(),
                ),
            )
            if suppress_pending:
                self._connection.execute(
                    """
                    UPDATE notification_outbox
                    SET status = 'suppressed',
                        leased_until_utc = NULL,
                        last_error_category = 'notifications_paused',
                        last_error_message = 'Notification suppressed by owner policy'
                    WHERE channel = ? AND recipient = ? AND topic = ?
                      AND status IN ('pending', 'leased')
                    """,
                    (CHANNEL, RECIPIENT, TOPIC),
                )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return NotificationPolicy(
            mode=mode,
            paused_until=paused_until,
            changed_at=changed_at,
        )

    def _delivery(self, delivery_id: int) -> NotificationDelivery:
        row = self._connection.execute(
            """
            SELECT id, event_type, device_id, alert_type, incident_id,
                   transition_id, occurred_at_utc, payload_json,
                   attempt_count, coalesced_count
            FROM notification_outbox
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("claimed notification was not found")
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError) as error:
            raise sqlite3.DatabaseError("notification payload is invalid") from error
        if not isinstance(payload, dict):
            raise sqlite3.DatabaseError("notification payload is invalid")
        return NotificationDelivery(
            id=int(row["id"]),
            event_type=NotificationEventType(str(row["event_type"])),
            device_id=str(row["device_id"]),
            alert_type=AlertType(str(row["alert_type"])),
            incident_id=int(row["incident_id"]),
            transition_id=int(row["transition_id"]),
            occurred_at=datetime.fromisoformat(row["occurred_at_utc"]),
            payload=payload,
            attempt_count=int(row["attempt_count"]),
            coalesced_count=int(row["coalesced_count"]),
        )


def _policy_from_row(row: sqlite3.Row) -> NotificationPolicy:
    return NotificationPolicy(
        mode=NotificationPolicyMode(str(row["mode"])),
        paused_until=_optional_datetime(row["paused_until_utc"]),
        changed_at=_optional_datetime(row["changed_at_utc"]),
    )


def _runtime_from_row(row: sqlite3.Row) -> NotificationDeliveryRuntime:
    outcome = row["last_outcome"]
    return NotificationDeliveryRuntime(
        last_started_at=datetime.fromisoformat(row["last_started_at_utc"]),
        last_finished_at=_optional_datetime(row["last_finished_at_utc"]),
        last_outcome=None if outcome is None else NotificationRuntimeOutcome(str(outcome)),
        delivered_count=int(row["delivered_count"]),
        failed_count=int(row["failed_count"]),
        last_error_category=_optional_text(row["last_error_category"]),
        last_error_message=_optional_text(row["last_error_message"]),
    )


def _optional_datetime(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _safe_text(value: str, *, fallback: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    return (collapsed or fallback)[:limit]


def _require_row(cursor: sqlite3.Cursor, message: str) -> None:
    if cursor.rowcount != 1:
        raise sqlite3.DatabaseError(message)
