"""Stateless Telegram conversation for deliberate owner-only AC control."""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from personal_edge_lab.domain.ac import (
    AcMode,
    AcState,
    CommandAuditEntry,
    CommandExecution,
    CommandOutcome,
    CommandRequestContext,
    FanSpeed,
    ValidationError,
    VerticalVane,
)
from personal_edge_lab.infrastructure.telegram.bot_api import TelegramApiError
from personal_edge_lab.modules.ac_control import (
    CommandConflictError,
    CommandInProgressError,
    CommandRateLimitedError,
    DeviceBusyError,
)

EMPTY_KEYBOARD: Mapping[str, object] = {"inline_keyboard": []}
FANS = tuple(FanSpeed)
VANES = tuple(VerticalVane)


class TelegramGateway(Protocol):
    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]: ...

    def edit_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Mapping[str, object] | None = None,
    ) -> None: ...

    def answer_callback(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None: ...


CommandExecutor = Callable[
    [CommandRequestContext, str, Mapping[str, object] | None],
    CommandExecution,
]
StateProvider = Callable[[], "PanelState"]


@dataclass(frozen=True, slots=True)
class PanelState:
    temperature_c: int = 24
    fan: FanSpeed = FanSpeed.AUTO
    vertical_vane: VerticalVane = VerticalVane.MIDDLE

    def as_command_payload(self) -> dict[str, object]:
        return {
            "power": True,
            "temperature_c": self.temperature_c,
            "mode": AcMode.COOL.value,
            "fan": self.fan.value,
            "vertical_vane": self.vertical_vane.value,
        }


class TelegramAcControl:
    def __init__(
        self,
        *,
        gateway: TelegramGateway,
        owner_user_id: int,
        execute_command: CommandExecutor,
        state_provider: StateProvider = PanelState,
        command_rate_limit: int = 6,
        command_timeout_seconds: float = 5,
    ) -> None:
        self._gateway = gateway
        self._owner_user_id = owner_user_id
        self._execute_command = execute_command
        self._state_provider = state_provider
        self._command_rate_limit = command_rate_limit
        self._command_timeout_seconds = command_timeout_seconds

    def handle_update(self, update: Mapping[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(update, message)
            return
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)

    def _handle_message(
        self,
        update: Mapping[str, Any],
        message: Mapping[str, Any],
    ) -> None:
        identity = _private_identity(message)
        if identity != (self._owner_user_id, self._owner_user_id):
            return
        text = message.get("text")
        if not isinstance(text, str):
            return
        command = text.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
        if command == "/ac":
            state = self._state_provider()
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=_panel_text(state),
                reply_markup=_panel_keyboard(state),
            )
            return
        if command == "/off":
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                return
            token = _idempotency_token(f"message:{update_id}")
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=_off_review_text(),
                reply_markup=_off_review_keyboard(token),
            )
            return
        if command in {"/start", "/help"}:
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=(
                    "Casadaqui · RUBIK AC control\n\n"
                    "/ac — open the control panel\n"
                    "/off — review a Power Off request\n"
                    "/help — show this message\n\n"
                    "Every physical action requires an explicit confirmation."
                ),
            )
            return
        if command.startswith("/"):
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text="Unknown command. Use /ac to control the air conditioner.",
            )

    def _handle_callback(self, callback: Mapping[str, Any]) -> None:
        callback_id = callback.get("id")
        message = callback.get("message")
        sender = callback.get("from")
        data = callback.get("data")
        if (
            not isinstance(callback_id, str)
            or not isinstance(message, dict)
            or not isinstance(sender, dict)
            or not isinstance(data, str)
        ):
            return
        identity = _private_identity(message, sender=sender)
        if identity != (self._owner_user_id, self._owner_user_id):
            self._gateway.answer_callback(
                callback_query_id=callback_id,
                text="This control is private.",
                show_alert=True,
            )
            return
        message_id = message.get("message_id")
        if not isinstance(message_id, int):
            return

        try:
            self._dispatch_callback(callback_id, message_id, data)
        except (ValueError, ValidationError):
            self._gateway.answer_callback(
                callback_query_id=callback_id,
                text="This control is invalid or has expired.",
                show_alert=True,
            )

    def _dispatch_callback(self, callback_id: str, message_id: int, data: str) -> None:
        if data == "noop":
            self._gateway.answer_callback(callback_query_id=callback_id)
            return
        if data == "review_off":
            token = _idempotency_token(f"callback:{callback_id}")
            self._gateway.answer_callback(callback_query_id=callback_id)
            self._gateway.edit_message(
                chat_id=self._owner_user_id,
                message_id=message_id,
                text=_off_review_text(),
                reply_markup=_off_review_keyboard(token),
            )
            return

        parts = data.split(":")
        action = parts[0]
        if action in {"panel", "review_set", "cancel"}:
            state = _state_from_parts(parts[1:])
            self._gateway.answer_callback(callback_query_id=callback_id)
            if action == "panel" or action == "cancel":
                self._gateway.edit_message(
                    chat_id=self._owner_user_id,
                    message_id=message_id,
                    text=_panel_text(state),
                    reply_markup=_panel_keyboard(state),
                )
            else:
                token = _idempotency_token(f"callback:{callback_id}")
                self._gateway.edit_message(
                    chat_id=self._owner_user_id,
                    message_id=message_id,
                    text=_set_review_text(state),
                    reply_markup=_set_review_keyboard(token, state),
                )
            return
        if action == "confirm_set":
            if len(parts) != 5:
                raise ValueError("invalid set confirmation")
            token = _validated_token(parts[1])
            state = _state_from_parts(parts[2:])
            self._confirm(
                callback_id=callback_id,
                message_id=message_id,
                token=token,
                command_type="set_state",
                state_payload=state.as_command_payload(),
            )
            return
        if action == "confirm_off":
            if len(parts) != 2:
                raise ValueError("invalid off confirmation")
            self._confirm(
                callback_id=callback_id,
                message_id=message_id,
                token=_validated_token(parts[1]),
                command_type="power_off",
                state_payload=None,
            )
            return
        raise ValueError("unknown callback action")

    def _confirm(
        self,
        *,
        callback_id: str,
        message_id: int,
        token: str,
        command_type: str,
        state_payload: Mapping[str, object] | None,
    ) -> None:
        # A redelivered callback may already be too old to answer. The message edit below is still
        # a required delivery gate before any physical request can begin.
        with contextlib.suppress(TelegramApiError):
            self._gateway.answer_callback(
                callback_query_id=callback_id,
                text="Sending one command…",
            )
        self._gateway.edit_message(
            chat_id=self._owner_user_id,
            message_id=message_id,
            text="Sending one AC command through RUBIK…",
            reply_markup=EMPTY_KEYBOARD,
        )
        context = CommandRequestContext(
            actor_id=f"telegram:{self._owner_user_id}",
            request_source="telegram_bot",
            idempotency_key=f"tg-{token}",
            rate_limit=self._command_rate_limit,
            rate_window_seconds=60,
            lock_lease_seconds=self._command_timeout_seconds + 10,
        )
        try:
            execution = self._execute_command(context, command_type, state_payload)
        except CommandRateLimitedError as error:
            text = (
                "Command limit reached\n\n"
                f"Wait approximately {error.retry_after_seconds} seconds, then open /ac again."
            )
        except (CommandConflictError, CommandInProgressError, DeviceBusyError):
            text = (
                "Another command is already in progress\n\n"
                "No additional physical request was sent. Wait, then open /ac again."
            )
        except (OSError, sqlite3.Error):
            text = (
                "⚠️ Physical outcome unknown\n\n"
                "RUBIK could not record a reliable result. The command may have been transmitted. "
                "Do not automatically send it again; inspect Activity in the dashboard."
            )
        else:
            text = _result_text(execution)
        self._gateway.edit_message(
            chat_id=self._owner_user_id,
            message_id=message_id,
            text=text,
            reply_markup=EMPTY_KEYBOARD,
        )


def latest_requested_state(entries: Sequence[CommandAuditEntry]) -> PanelState:
    for entry in entries:
        if entry.command_type != "set_state":
            continue
        try:
            payload = json.loads(entry.command_payload_json)
            if not isinstance(payload, dict):
                continue
            state = AcState.from_values(
                power=payload.get("power"),
                temperature_c=payload.get("temperature_c"),
                mode=payload.get("mode"),
                fan=payload.get("fan"),
                vertical_vane=payload.get("vertical_vane"),
            )
        except (json.JSONDecodeError, ValidationError):
            continue
        if state.power and state.mode is AcMode.COOL:
            return PanelState(state.temperature_c, state.fan, state.vertical_vane)
    return PanelState()


def _private_identity(
    message: Mapping[str, Any],
    *,
    sender: Mapping[str, Any] | None = None,
) -> tuple[int, int] | None:
    chat = message.get("chat")
    author = sender or message.get("from")
    if not isinstance(chat, dict) or not isinstance(author, dict):
        return None
    chat_id = chat.get("id")
    user_id = author.get("id")
    if (
        chat.get("type") != "private"
        or not isinstance(chat_id, int)
        or not isinstance(user_id, int)
    ):
        return None
    return user_id, chat_id


def _state_from_parts(parts: Sequence[str]) -> PanelState:
    if len(parts) != 3:
        raise ValueError("invalid panel state")
    temperature = int(parts[0])
    if not 16 <= temperature <= 31:
        raise ValueError("invalid temperature")
    return PanelState(
        temperature_c=temperature,
        fan=FanSpeed(parts[1]),
        vertical_vane=VerticalVane(parts[2]),
    )


def _state_data(prefix: str, state: PanelState) -> str:
    data = f"{prefix}:{state.temperature_c}:{state.fan.value}:{state.vertical_vane.value}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Telegram callback data exceeds 64 bytes")
    return data


def _idempotency_token(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def _validated_token(value: str) -> str:
    if len(value) != 20 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid confirmation token")
    return value


def _button(text: str, data: str) -> dict[str, str]:
    if not 1 <= len(data.encode("utf-8")) <= 64:
        raise ValueError("Telegram callback data must be from 1 through 64 bytes")
    return {"text": text, "callback_data": data}


def _panel_text(state: PanelState) -> str:
    return (
        "RUBIK · AIR CONDITIONER\n\n"
        "Last requested settings — not current AC state.\n\n"
        "Mode: Cool\n"
        f"Temperature: {state.temperature_c} °C\n"
        f"Fan: {_label(state.fan.value)}\n"
        f"Vertical vane: {_label(state.vertical_vane.value)}\n\n"
        "Adjust the request, then review it before sending."
    )


def _panel_keyboard(state: PanelState) -> Mapping[str, object]:
    lower = PanelState(max(16, state.temperature_c - 1), state.fan, state.vertical_vane)
    higher = PanelState(min(31, state.temperature_c + 1), state.fan, state.vertical_vane)
    next_fan = PanelState(
        state.temperature_c,
        _next_value(FANS, state.fan),
        state.vertical_vane,
    )
    next_vane = PanelState(
        state.temperature_c,
        state.fan,
        _next_value(VANES, state.vertical_vane),
    )
    return {
        "inline_keyboard": [
            [
                _button("−", _state_data("panel", lower)),
                _button(f"{state.temperature_c} °C", "noop"),
                _button("+", _state_data("panel", higher)),
            ],
            [_button(f"Fan · {_label(state.fan.value)}", _state_data("panel", next_fan))],
            [
                _button(
                    f"Vane · {_label(state.vertical_vane.value)}",
                    _state_data("panel", next_vane),
                )
            ],
            [_button("Review settings", _state_data("review_set", state))],
            [_button("Power off", "review_off")],
        ]
    }


def _set_review_text(state: PanelState) -> str:
    return (
        "REVIEW AC COMMAND\n\n"
        "Set requested state:\n"
        "Power: On\n"
        "Mode: Cool\n"
        f"Temperature: {state.temperature_c} °C\n"
        f"Fan: {_label(state.fan.value)}\n"
        f"Vertical vane: {_label(state.vertical_vane.value)}\n\n"
        "Confirm sends exactly one request. A successful response still does not prove the "
        "physical AC state."
    )


def _set_review_keyboard(token: str, state: PanelState) -> Mapping[str, object]:
    return {
        "inline_keyboard": [
            [
                _button("Back", _state_data("cancel", state)),
                _button("Confirm", _state_data(f"confirm_set:{token}", state)),
            ]
        ]
    }


def _off_review_text() -> str:
    return (
        "REVIEW AC COMMAND\n\n"
        "Power Off\n\n"
        "Confirm sends exactly one power-off request. The recorded result does not prove the "
        "physical AC state."
    )


def _off_review_keyboard(token: str) -> Mapping[str, object]:
    return {
        "inline_keyboard": [
            [
                _button("Cancel", "cancel:24:auto:middle"),
                _button("Confirm Power Off", f"confirm_off:{token}"),
            ]
        ]
    }


def _result_text(execution: CommandExecution) -> str:
    outcome = execution.result.outcome
    replay_note = (
        "\nRecorded result recovered safely; no duplicate request was sent."
        if execution.replayed
        else ""
    )
    if outcome is CommandOutcome.CONFIRMED_SUCCESS:
        heading = "✅ AC command confirmed"
        detail = "The controller accepted the request."
    elif outcome is CommandOutcome.REJECTED_LOCALLY:
        heading = "Command rejected locally"
        detail = "RUBIK did not contact the AC controller."
    elif outcome is CommandOutcome.NODE_UNREACHABLE:
        heading = "AC controller unreachable"
        detail = "No successful delivery was confirmed."
    elif outcome is CommandOutcome.NODE_REPORTED_FAILURE:
        heading = "AC controller reported a failure"
        detail = "The controller did not accept the command."
    else:
        heading = "⚠️ Physical outcome unknown"
        detail = (
            "The request may have reached the controller. Do not automatically send it again; "
            "inspect Activity in the dashboard."
        )
    return f"{heading}\n\n{detail}\nAudit #{execution.command_id}{replay_note}"


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _next_value[T](values: Sequence[T], current: T) -> T:
    index = values.index(current)
    return values[(index + 1) % len(values)]
