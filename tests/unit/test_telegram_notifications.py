from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from personal_edge_lab.apps.telegram_bot.capabilities.notifications import (
    NotificationsCapability,
)
from personal_edge_lab.apps.telegram_bot.delivery import (
    TelegramNotificationSender,
    notification_text,
)
from personal_edge_lab.apps.telegram_bot.owner_bot import OwnerBot
from personal_edge_lab.domain.alerting import AlertType
from personal_edge_lab.domain.notifications import (
    NotificationDelivery,
    NotificationEventType,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.infrastructure.persistence.sqlite.notifications import (
    SqliteNotificationRepository,
)
from personal_edge_lab.modules.notifications import ManageNotificationPolicy

OWNER_ID = 112233
NOW = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.answered: list[dict[str, Any]] = []

    def send_message(self, **payload: Any) -> dict[str, Any]:
        self.sent.append(payload)
        return {"message_id": 42}

    def edit_message(self, **payload: Any) -> None:
        self.edited.append(payload)

    def answer_callback(self, **payload: Any) -> None:
        self.answered.append(payload)


def message_update(text: str) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "text": text,
            "from": {"id": OWNER_ID},
            "chat": {"id": OWNER_ID, "type": "private"},
        },
    }


def callback_update(data: str) -> dict[str, Any]:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "callback-1",
            "data": data,
            "from": {"id": OWNER_ID},
            "message": {
                "message_id": 10,
                "chat": {"id": OWNER_ID, "type": "private"},
            },
        },
    }


def notifications_bot(tmp_path, gateway: FakeGateway) -> OwnerBot:
    database = tmp_path / "notifications.db"
    run_migrations(database)
    policy = ManageNotificationPolicy(
        lambda: SqliteNotificationRepository(database),
        clock=lambda: NOW,
    )
    capability = NotificationsCapability(
        gateway=gateway,
        policy=policy,
        owner_timezone=ZoneInfo("Europe/Madrid"),
        clock=lambda: NOW,
    )
    return OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(capability,),
    )


def test_owner_can_pause_indefinitely_and_resume_without_backlog(tmp_path) -> None:
    gateway = FakeGateway()
    bot = notifications_bot(tmp_path, gateway)

    bot.handle_update(message_update("/notifications"))
    assert "Estado: <b>activas</b>" in gateway.sent[-1]["text"]

    bot.handle_update(callback_update("notifications:pause_forever"))
    assert "indefinidamente" in gateway.edited[-1]["text"]
    assert (
        gateway.edited[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        == "notifications:resume"
    )

    bot.handle_update(callback_update("notifications:resume"))
    assert "NOTIFICACIONES REACTIVADAS" in gateway.edited[-1]["text"]
    assert "alertas anteriores no se enviarán" in gateway.edited[-1]["text"]


def test_pause_until_tomorrow_uses_owner_timezone(tmp_path) -> None:
    gateway = FakeGateway()
    bot = notifications_bot(tmp_path, gateway)

    bot.handle_update(callback_update("notifications:pause_tomorrow"))

    assert "27/07 · 08:00" in gateway.edited[-1]["text"]


def delivery(
    *,
    event_type: NotificationEventType,
    coalesced_count: int = 1,
) -> NotificationDelivery:
    return NotificationDelivery(
        id=1,
        event_type=event_type,
        device_id="ac-controller-01",
        alert_type=AlertType.TELEMETRY_STALE,
        incident_id=7,
        transition_id=9,
        occurred_at=NOW,
        payload={
            "suspect_started_at_utc": (NOW - timedelta(minutes=3)).isoformat(),
            "alerting_at_utc": (NOW - timedelta(minutes=2)).isoformat(),
            "recovered_at_utc": NOW.isoformat(),
            "evidence_category": "stale",
        },
        attempt_count=1,
        coalesced_count=coalesced_count,
    )


def test_notification_renderer_is_concise_and_supports_instability() -> None:
    started = notification_text(
        delivery(event_type=NotificationEventType.OPERATIONAL_ALERT_STARTED)
    )
    recovered = notification_text(
        delivery(event_type=NotificationEventType.OPERATIONAL_ALERT_RECOVERED)
    )
    unstable = notification_text(
        delivery(
            event_type=NotificationEventType.OPERATIONAL_ALERT_STARTED,
            coalesced_count=4,
        )
    )

    assert "TELEMETRÍA INTERRUMPIDA" in started
    assert "3 min" in started
    assert "TELEMETRÍA RECUPERADA" in recovered
    assert "Interrupción: 2 min" in recovered
    assert "TELEMETRÍA INESTABLE" in unstable
    assert "4 veces" in unstable


def test_sender_uses_status_open_button() -> None:
    gateway = FakeGateway()
    sender = TelegramNotificationSender(gateway=gateway, owner_user_id=OWNER_ID)

    message_id = sender.send(delivery(event_type=NotificationEventType.OPERATIONAL_ALERT_STARTED))

    assert message_id == "42"
    assert (
        gateway.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "status:open"
    )
