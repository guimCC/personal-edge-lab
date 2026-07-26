from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from personal_edge_lab.apps.telegram_bot.control import (
    PanelState,
    TelegramAcControl,
    latest_requested_state,
)
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

OWNER_ID = 112233


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


def test_only_the_configured_private_owner_can_open_controls() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
    )

    control.handle_update(message_update("/ac", user_id=999))
    control.handle_update(
        {
            "update_id": 2,
            "message": {
                "text": "/ac",
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

    assert "Last requested settings — not current AC state" in gateway.sent[0]["text"]
    buttons = gateway.sent[0]["reply_markup"]["inline_keyboard"]
    assert all(
        1 <= len(button["callback_data"].encode()) <= 64 for row in buttons for button in row
    )
    assert executor.calls == []


def test_set_state_requires_review_and_reuses_confirmation_idempotency_key() -> None:
    gateway = FakeGateway()
    executor = RecordingExecutor()
    control = TelegramAcControl(
        gateway=gateway,
        owner_user_id=OWNER_ID,
        execute_command=executor,
        state_provider=lambda: PanelState(25, FanSpeed.HIGH, VerticalVane.LOW),
    )
    control.handle_update(message_update("/ac"))
    review = keyboard_callback(gateway.sent[0], 3)

    control.handle_update(callback_update(review, callback_id="review-query"))

    assert executor.calls == []
    assert "REVIEW AC COMMAND" in gateway.edited[-1]["text"]
    confirm = keyboard_callback(gateway.edited[-1], 0, 1)

    control.handle_update(callback_update(confirm, callback_id="confirm-query-1"))
    control.handle_update(callback_update(confirm, callback_id="confirm-query-2"))

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
    assert "no duplicate request was sent" in gateway.edited[-1]["text"]


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
    assert "AC command confirmed" in gateway.edited[-1]["text"]


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
