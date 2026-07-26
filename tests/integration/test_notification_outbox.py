from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from personal_edge_lab.domain.alerting import AlertPolicy
from personal_edge_lab.domain.notifications import NotificationPolicyMode
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.infrastructure.persistence.sqlite.alert_evaluation import (
    SqliteAlertEvaluationRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.notifications import (
    SqliteNotificationRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.telemetry import (
    SqliteTelemetryRepository,
)
from personal_edge_lab.modules.alerting import EvaluateOperationalAlerts
from personal_edge_lab.modules.notifications import (
    DrainNotificationOutbox,
    ManageNotificationPolicy,
    NotificationSendFailure,
)

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
POLICY = AlertPolicy(
    telemetry_suspect_after_seconds=45,
    telemetry_alert_after_seconds=180,
    edge_min_consecutive_failures=4,
    edge_alert_after_seconds=45,
    recovery_display_seconds=300,
)


def reading(at: datetime) -> TemperatureReading:
    return TemperatureReading.from_payload(
        {
            "sensor": "thermistor",
            "temperature_c": 24.5,
            "raw_adc": 1700,
            "age_ms": 500,
            "sample_interval_ms": 2000,
        },
        device_id="node-1",
        received_at=at,
    )


def evaluate(database, at: datetime) -> None:
    EvaluateOperationalAlerts(
        lambda: SqliteAlertEvaluationRepository(database),
        device_id="node-1",
        policy=POLICY,
        clock=lambda: at,
    ).execute()


def create_alert(database) -> None:
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW - timedelta(minutes=10)))
    evaluate(database, NOW)
    evaluate(database, NOW + timedelta(seconds=1))


def outbox_rows(database) -> list[tuple[object, ...]]:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT event_type, status, attempt_count, coalesced_count,
                   last_error_category
            FROM notification_outbox
            ORDER BY id
            """
        ).fetchall()


def test_notifiable_transitions_are_enqueued_and_pause_suppresses_without_backlog(
    tmp_path,
) -> None:
    database = tmp_path / "notifications.db"
    run_migrations(database)
    create_alert(database)

    assert outbox_rows(database) == [("operational_alert_started", "pending", 0, 1, None)]

    manager = ManageNotificationPolicy(
        lambda: SqliteNotificationRepository(database),
        clock=lambda: NOW + timedelta(seconds=2),
    )
    manager.pause_indefinitely()
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW + timedelta(seconds=3)))
    evaluate(database, NOW + timedelta(seconds=3))

    assert outbox_rows(database) == [
        (
            "operational_alert_started",
            "suppressed",
            0,
            1,
            "notifications_paused",
        ),
        (
            "operational_alert_recovered",
            "suppressed",
            0,
            1,
            "notifications_paused",
        ),
    ]

    manager.resume()
    overview = manager.get()
    assert overview.policy.mode is NotificationPolicyMode.ENABLED
    assert overview.pending_count == 0


def test_transition_and_notification_roll_back_together(tmp_path) -> None:
    database = tmp_path / "atomic.db"
    run_migrations(database)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW - timedelta(minutes=10)))
    evaluate(database, NOW)

    class FailingOutboxRepository(SqliteAlertEvaluationRepository):
        def enqueue_notification(self, notification) -> None:
            raise sqlite3.OperationalError("simulated outbox failure")

    evaluator = EvaluateOperationalAlerts(
        lambda: FailingOutboxRepository(database),
        device_id="node-1",
        policy=POLICY,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    with pytest.raises(sqlite3.OperationalError, match="outbox"):
        evaluator.execute()

    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM alert_incidents WHERE status = 'active'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0


def test_concurrent_claim_has_exactly_one_winner(tmp_path) -> None:
    database = tmp_path / "claim.db"
    run_migrations(database)
    create_alert(database)

    def claim(_index: int):
        with SqliteNotificationRepository(database) as repository:
            return repository.claim_due(
                now=NOW + timedelta(seconds=2),
                limit=20,
                lease_seconds=60,
                max_age_seconds=86400,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))

    assert sorted(len(result) for result in results) == [0, 1]
    assert sum(delivery.attempt_count for result in results for delivery in result) == 1


def test_delivery_records_success_and_structured_retry(tmp_path) -> None:
    database = tmp_path / "delivery.db"
    run_migrations(database)
    create_alert(database)

    class RateLimitedSender:
        def send(self, delivery):
            raise NotificationSendFailure(
                category="rate_limited",
                message="Telegram rejected the request (code 429)",
                retry_after_seconds=200,
            )

    DrainNotificationOutbox(
        lambda: SqliteNotificationRepository(database),
        sender=RateLimitedSender(),
        batch_size=20,
        lease_seconds=60,
        max_age_seconds=86400,
        clock=lambda: NOW + timedelta(seconds=2),
    ).execute()

    with sqlite3.connect(database) as connection:
        status, attempts, next_attempt, category = connection.execute(
            """
            SELECT status, attempt_count, next_attempt_at_utc, last_error_category
            FROM notification_outbox
            """
        ).fetchone()
    assert status == "pending"
    assert attempts == 1
    assert datetime.fromisoformat(next_attempt) == NOW + timedelta(seconds=202)
    assert category == "rate_limited"

    class SuccessfulSender:
        def send(self, delivery):
            return "telegram-42"

    DrainNotificationOutbox(
        lambda: SqliteNotificationRepository(database),
        sender=SuccessfulSender(),
        batch_size=20,
        lease_seconds=60,
        max_age_seconds=86400,
        clock=lambda: NOW + timedelta(seconds=203),
    ).execute()

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status, attempt_count, external_message_id FROM notification_outbox"
        ).fetchone() == ("delivered", 2, "telegram-42")


def test_third_flap_is_deferred_and_coalesces_newer_events(tmp_path) -> None:
    database = tmp_path / "flapping.db"
    run_migrations(database)
    create_alert(database)
    with SqliteTelemetryRepository(database) as repository:
        repository.insert(reading(NOW + timedelta(minutes=2)))
    evaluate(database, NOW + timedelta(minutes=2))
    evaluate(database, NOW + timedelta(minutes=3))
    evaluate(database, NOW + timedelta(minutes=6))

    rows = outbox_rows(database)
    assert [row[3] for row in rows] == [1, 1, 3]
    with sqlite3.connect(database) as connection:
        next_attempt = connection.execute(
            "SELECT next_attempt_at_utc FROM notification_outbox ORDER BY id DESC"
        ).fetchone()[0]
    assert datetime.fromisoformat(next_attempt) == NOW + timedelta(minutes=15, seconds=1)
