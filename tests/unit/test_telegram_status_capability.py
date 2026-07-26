from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from personal_edge_lab.apps.telegram_bot.capabilities.status import (
    StatusCapability,
    TelegramStatusSnapshot,
    status_text,
)
from personal_edge_lab.apps.telegram_bot.owner_bot import OwnerBot
from personal_edge_lab.domain.notifications import (
    NotificationDeliveryRuntime,
    NotificationOverview,
    NotificationPolicy,
    NotificationPolicyMode,
    NotificationRuntimeOutcome,
)
from personal_edge_lab.modules.alerting import AlertOverview, AlertStatusSummary
from personal_edge_lab.modules.platform_status import PlatformHealth, PlatformHealthStatus
from personal_edge_lab.modules.telemetry import (
    CollectorHealth,
    CollectorHealthStatus,
    EdgeNodeHealth,
    EdgeNodeHealthStatus,
    TelemetryFreshness,
    TelemetryHealth,
)

OWNER_ID = 112233
NOW = datetime(2026, 7, 26, 1, 30, tzinfo=UTC)


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.answered: list[dict[str, Any]] = []

    def send_message(self, **payload: Any) -> dict[str, Any]:
        self.sent.append(payload)
        return {"message_id": 1}

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


def healthy_status() -> TelegramStatusSnapshot:
    return TelegramStatusSnapshot(
        api_reachable=True,
        version="0.7.2",
        platform=PlatformHealth(
            status=PlatformHealthStatus.HEALTHY,
            checked_at=NOW,
            telemetry=TelemetryHealth(
                status=TelemetryFreshness.FRESH,
                device_id="ac-controller-01",
                last_received_at=NOW - timedelta(seconds=8),
                age_seconds=8,
                stale_after_seconds=45,
            ),
            collector=CollectorHealth(
                status=CollectorHealthStatus.RUNNING,
                device_id="ac-controller-01",
                process_started_at=NOW - timedelta(days=1),
                heartbeat_at=NOW - timedelta(seconds=8),
                heartbeat_age_seconds=8,
                stale_after_seconds=45,
                stopped_at=None,
                last_attempt_at=NOW - timedelta(seconds=8),
                last_success_at=NOW - timedelta(seconds=8),
                consecutive_failures=0,
            ),
            edge_node=EdgeNodeHealth(
                status=EdgeNodeHealthStatus.REACHABLE,
                device_id="ac-controller-01",
                last_attempt_at=NOW - timedelta(seconds=8),
                last_success_at=NOW - timedelta(seconds=8),
                last_failure_at=None,
                last_failure_category=None,
                last_failure_message=None,
            ),
            alerts=AlertOverview(
                device_id="ac-controller-01",
                status=AlertStatusSummary.HEALTHY,
                active_count=0,
                suspect_count=0,
                latest_transition_at=None,
                evaluator_last_run_at=NOW - timedelta(seconds=10),
                evaluator_age_seconds=10,
                states=(),
                incidents=(),
                limit=1,
            ),
        ),
    )


def status_bot(gateway: FakeGateway, provider: Any) -> OwnerBot:
    capability = StatusCapability(
        gateway=gateway,
        status_provider=provider,
        version="0.7.2",
    )
    return OwnerBot(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        capabilities=(capability,),
    )


def test_status_shows_shared_health_and_refreshes_in_place() -> None:
    gateway = FakeGateway()
    calls = 0

    def provider() -> TelegramStatusSnapshot:
        nonlocal calls
        calls += 1
        return healthy_status()

    bot = status_bot(gateway, provider)
    bot.handle_update(message_update("/status"))

    assert calls == 1
    assert "<b>API</b> · disponible" in gateway.sent[-1]["text"]
    assert "<b>Colector</b> · activo · 8 s" in gateway.sent[-1]["text"]
    assert "<b>ESP32</b> · accesible · 8 s" in gateway.sent[-1]["text"]
    assert "<b>Telemetría</b> · fresca · 8 s" in gateway.sent[-1]["text"]
    assert "<b>Alertas</b> · normal · 10 s" in gateway.sent[-1]["text"]
    keyboard = gateway.sent[-1]["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == "status:refresh"

    bot.handle_update(callback_update("status:refresh"))

    assert calls == 2
    assert gateway.edited[-1]["message_id"] == 10
    assert gateway.answered[-1]["text"] == "Estado actualizado"


def test_legacy_status_refresh_remains_compatible() -> None:
    gateway = FakeGateway()
    bot = status_bot(gateway, healthy_status)

    bot.handle_update(callback_update("refresh_status"))

    assert "<b>Estado general · OPERATIVO</b>" in gateway.edited[-1]["text"]


def test_status_distinguishes_each_degraded_component() -> None:
    healthy = healthy_status()
    degraded = TelegramStatusSnapshot(
        api_reachable=False,
        version=healthy.version,
        platform=replace(
            healthy.platform,
            status=PlatformHealthStatus.DEGRADED,
            telemetry=replace(
                healthy.platform.telemetry,
                status=TelemetryFreshness.STALE,
                age_seconds=75,
            ),
            collector=replace(
                healthy.platform.collector,
                status=CollectorHealthStatus.STALE,
                heartbeat_age_seconds=75,
            ),
            edge_node=replace(
                healthy.platform.edge_node,
                status=EdgeNodeHealthStatus.UNREACHABLE,
            ),
            alerts=replace(
                healthy.platform.alerts,
                status=AlertStatusSummary.ALERTING,
                active_count=2,
            ),
        ),
    )

    text = status_text(degraded)

    assert "<b>API</b> · no responde" in text
    assert "<b>Colector</b> · sin pulso reciente · 1 min" in text
    assert "<b>ESP32</b> · no disponible" in text
    assert "<b>Telemetría</b> · atrasada · 1 min" in text
    assert "<b>Alertas</b> · 2 incidencias activas" in text
    assert "<b>Estado general · DEGRADADO</b>" in text


def test_status_database_failure_is_sanitized() -> None:
    gateway = FakeGateway()

    def unavailable_status() -> TelegramStatusSnapshot:
        raise OSError("sensitive local database detail")

    bot = status_bot(gateway, unavailable_status)
    bot.handle_update(message_update("/status"))

    assert "<b>ESTADO NO DISPONIBLE</b>" in gateway.sent[-1]["text"]
    assert "sensitive" not in gateway.sent[-1]["text"]


def test_status_distinguishes_operational_paused_and_failed_notifications() -> None:
    healthy = healthy_status()
    runtime = NotificationDeliveryRuntime(
        last_started_at=NOW - timedelta(seconds=5),
        last_finished_at=NOW - timedelta(seconds=5),
        last_outcome=NotificationRuntimeOutcome.SUCCESS,
        delivered_count=0,
        failed_count=0,
        last_error_category=None,
        last_error_message=None,
    )
    operational = replace(
        healthy,
        notifications_enabled=True,
        notifications=NotificationOverview(
            policy=NotificationPolicy(
                mode=NotificationPolicyMode.ENABLED,
                paused_until=None,
                changed_at=NOW - timedelta(minutes=1),
            ),
            pending_count=0,
            failed_pending_count=0,
            oldest_pending_at=None,
            runtime=runtime,
        ),
    )
    assert "<b>Notificaciones</b> · operativas" in status_text(operational)

    paused = replace(
        operational,
        notifications=replace(
            operational.notifications,
            policy=NotificationPolicy(
                mode=NotificationPolicyMode.PAUSED_INDEFINITELY,
                paused_until=None,
                changed_at=NOW,
            ),
        ),
    )
    assert "pausadas indefinidamente" in status_text(paused)
    assert "<b>Estado general · OPERATIVO</b>" in status_text(paused)

    failed = replace(
        operational,
        notifications=replace(
            operational.notifications,
            pending_count=1,
            failed_pending_count=1,
            oldest_pending_at=NOW - timedelta(minutes=2),
        ),
    )
    assert "<b>Notificaciones</b> · entrega degradada" in status_text(failed)
    assert "<b>Estado general · DEGRADADO</b>" in status_text(failed)
