from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from personal_edge_lab.apps.telegram_bot.control import (
    PanelState,
    TelegramAcControl,
    latest_requested_state,
)
from personal_edge_lab.apps.telegram_bot.status import TelegramStatusSnapshot, status_text
from personal_edge_lab.domain.ac import (
    CommandAuditEntry,
    CommandExecution,
    CommandOutcome,
    CommandRequestContext,
    CommandResult,
    FanSpeed,
    VerticalVane,
)
from personal_edge_lab.infrastructure.telegram.bot_api import TelegramApiError
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


class ExpiredCallbackGateway(FakeGateway):
    def answer_callback(self, **payload: Any) -> None:
        self.answered.append(payload)
        raise TelegramApiError("Telegram rejected the request (code 400)")


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[CommandRequestContext, str, object]] = []

    def __call__(
        self,
        context: CommandRequestContext,
        command_type: str,
        state_payload: object,
    ) -> CommandExecution:
        self.calls.append((context, command_type, state_payload))
        return CommandExecution(
            command_id=42,
            command_type=command_type,
            payload_json=json.dumps(state_payload),
            result=CommandResult(CommandOutcome.CONFIRMED_SUCCESS, http_status=200),
            replayed=len(self.calls) > 1,
        )


def message_update(text: str, *, user_id: int = OWNER_ID, update_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10,
            "text": text,
            "from": {"id": user_id},
            "chat": {"id": user_id, "type": "private"},
        },
    }


def callback_update(data: str, *, callback_id: str = "callback-1") -> dict[str, Any]:
    return {
        "update_id": 2,
        "callback_query": {
            "id": callback_id,
            "data": data,
            "from": {"id": OWNER_ID},
            "message": {
                "message_id": 10,
                "chat": {"id": OWNER_ID, "type": "private"},
            },
        },
    }


def keyboard_callback(payload: dict[str, Any], row: int, column: int = 0) -> str:
    markup = payload["reply_markup"]
    return str(markup["inline_keyboard"][row][column]["callback_data"])


def healthy_status() -> TelegramStatusSnapshot:
    return TelegramStatusSnapshot(
        api_reachable=True,
        version="0.7.1",
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


def test_only_the_configured_private_owner_can_open_controls() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
    )

    control.handle_update(message_update("/ac", user_id=999))
    control.handle_update(message_update("/status", user_id=999, update_id=2))
    control.handle_update(
        {
            "update_id": 3,
            "message": {
                "text": "/status",
                "from": {"id": OWNER_ID},
                "chat": {"id": -1001, "type": "group"},
            },
        }
    )

    assert gateway.sent == []
    assert executor.calls == []


def test_panel_callbacks_are_bounded_and_do_not_send_a_command() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
    )

    control.handle_update(message_update("/ac"))

    assert "Última configuración solicitada" in gateway.sent[0]["text"]
    buttons = gateway.sent[0]["reply_markup"]["inline_keyboard"]
    assert all(
        1 <= len(button["callback_data"].encode()) <= 64 for row in buttons for button in row
    )
    assert buttons[0][1]["style"] == "primary"
    assert buttons[3][0]["style"] == "success"
    assert buttons[4][0]["style"] == "danger"
    assert executor.calls == []


def test_submenu_selection_returns_to_panel_without_sending() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
        state_provider=lambda: PanelState(25, FanSpeed.HIGH, VerticalVane.LOW),
    )
    control.handle_update(message_update("/ac"))
    fan_menu = keyboard_callback(gateway.sent[0], 1)

    control.handle_update(callback_update(fan_menu))

    assert executor.calls == []
    assert "VELOCIDAD DEL VENTILADOR" in gateway.edited[-1]["text"]
    select_low = keyboard_callback(gateway.edited[-1], 0, 1)

    control.handle_update(callback_update(select_low))

    assert executor.calls == []
    assert "Frío · Bajo · Baja" in gateway.edited[-1]["text"]


def test_status_shows_shared_operational_health_and_refreshes_in_place() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    calls = 0

    def status_provider() -> TelegramStatusSnapshot:
        nonlocal calls
        calls += 1
        return healthy_status()

    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
        status_provider=status_provider,
    )

    control.handle_update(message_update("/status"))

    assert calls == 1
    assert "<b>API</b> · disponible" in gateway.sent[-1]["text"]
    assert "<b>Colector</b> · activo · 8 s" in gateway.sent[-1]["text"]
    assert "<b>ESP32</b> · accesible · 8 s" in gateway.sent[-1]["text"]
    assert "<b>Telemetría</b> · fresca · 8 s" in gateway.sent[-1]["text"]
    assert "<b>Alertas</b> · normal · 10 s" in gateway.sent[-1]["text"]
    assert "<b>Estado general · OPERATIVO</b>" in gateway.sent[-1]["text"]
    refresh = keyboard_callback(gateway.sent[-1], 0)

    control.handle_update(callback_update(refresh))

    assert calls == 2
    assert gateway.edited[-1]["message_id"] == 10
    assert gateway.answered[-1]["text"] == "Estado actualizado"
    assert executor.calls == []


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


def test_status_database_failure_is_sanitized_and_does_not_send_a_command() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()

    def unavailable_status() -> TelegramStatusSnapshot:
        raise OSError("sensitive local database detail")

    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
        status_provider=unavailable_status,
    )

    control.handle_update(message_update("/status"))

    assert "<b>ESTADO NO DISPONIBLE</b>" in gateway.sent[-1]["text"]
    assert "sensitive" not in gateway.sent[-1]["text"]
    assert executor.calls == []


def test_send_state_reuses_panel_idempotency_key_without_a_review_screen() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
        state_provider=lambda: PanelState(25, FanSpeed.HIGH, VerticalVane.LOW),
    )
    control.handle_update(message_update("/ac"))
    send = keyboard_callback(gateway.sent[0], 3)

    control.handle_update(callback_update(send, callback_id="send-query-1"))
    control.handle_update(callback_update(send, callback_id="send-query-2"))

    assert len(executor.calls) == 2
    first_context, command_type, payload = executor.calls[0]
    second_context = executor.calls[1][0]
    assert command_type == "set_state"
    assert payload == {
        "power": True,
        "temperature_c": 25,
        "mode": "cool",
        "fan": "high",
        "vertical_vane": "low",
    }
    assert first_context.actor_id == f"telegram:{OWNER_ID}"
    assert first_context.request_source == "telegram_bot"
    assert first_context.idempotency_key == second_context.idempotency_key
    assert "no se ha repetido la petición" in gateway.edited[-1]["text"]


def test_off_shortcut_only_transmits_after_confirmation() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
    )

    control.handle_update(message_update("/off", update_id=71))
    assert executor.calls == []
    confirm = keyboard_callback(gateway.sent[0], 0, 1)

    control.handle_update(callback_update(confirm))

    assert len(executor.calls) == 1
    assert executor.calls[0][1:] == ("power_off", None)


def test_expired_callback_answer_can_still_replay_through_a_successful_message_edit() -> None:
    gateway = ExpiredCallbackGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
    )
    control.handle_update(message_update("/off", update_id=71))
    confirm = keyboard_callback(gateway.sent[0], 0, 1)

    control.handle_update(callback_update(confirm))

    assert len(executor.calls) == 1
    assert "ORDEN CONFIRMADA" in gateway.edited[-1]["text"]


def test_latest_requested_state_skips_invalid_and_non_cool_audit_payloads() -> None:
    now = datetime(2026, 7, 26, tzinfo=UTC)

    def entry(entry_id: int, payload: dict[str, object]) -> CommandAuditEntry:
        return CommandAuditEntry(
            id=entry_id,
            device_id="ac-controller-01",
            command_type="set_state",
            command_payload_json=json.dumps(payload),
            requested_at_utc=now,
            completed_at_utc=now,
            outcome=CommandOutcome.CONFIRMED_SUCCESS,
            http_status=200,
            response_body=None,
            error_category=None,
            error_message=None,
        )

    state = latest_requested_state(
        [
            entry(
                2,
                {
                    "power": True,
                    "temperature_c": 28,
                    "mode": "heat",
                    "fan": "auto",
                    "vertical_vane": "middle",
                },
            ),
            entry(
                1,
                {
                    "power": True,
                    "temperature_c": 23,
                    "mode": "cool",
                    "fan": "medium",
                    "vertical_vane": "swing",
                },
            ),
        ]
    )

    assert state == PanelState(23, FanSpeed.MEDIUM, VerticalVane.SWING)
