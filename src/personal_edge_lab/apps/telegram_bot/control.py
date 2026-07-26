"""Stateless Telegram conversation for deliberate owner-only AC control."""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from personal_edge_lab import __version__
from personal_edge_lab.apps.telegram_bot.status import (
    STATUS_KEYBOARD,
    TelegramStatusSnapshot,
    status_text,
    status_unavailable_text,
)
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
StatusProvider = Callable[[], TelegramStatusSnapshot]


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
        status_provider: StatusProvider | None = None,
        command_rate_limit: int = 6,
        command_timeout_seconds: float = 5,
    ) -> None:
        self._gateway = gateway
        self._owner_user_id = owner_user_id
        self._execute_command = execute_command
        self._state_provider = state_provider
        self._status_provider = status_provider
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
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                return
            state = self._state_provider()
            token = _idempotency_token(f"panel:{update_id}")
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=_panel_text(state),
                reply_markup=_panel_keyboard(token, state),
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
        if command == "/status":
            self._show_status()
            return
        if command in {"/start", "/help"}:
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=(
                    "🏠 <b>Casadaqui · Control del aire</b>\n\n"
                    "/ac — abrir el mando\n"
                    "/off — preparar el apagado\n"
                    "/status — ver el estado de RUBIK\n"
                    "/help — mostrar esta ayuda\n\n"
                    "Enviar ajuste transmite directamente la configuración visible. "
                    "Apagar requiere una confirmación adicional."
                ),
            )
            return
        if command.startswith("/"):
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text="Comando desconocido. Usa /ac para abrir el mando.",
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
                text="Este control es privado.",
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
                text="Este control no es válido o ha caducado.",
                show_alert=True,
            )

    def _dispatch_callback(self, callback_id: str, message_id: int, data: str) -> None:
        if data == "noop":
            self._gateway.answer_callback(callback_query_id=callback_id)
            return
        if data == "refresh_status":
            self._gateway.answer_callback(
                callback_query_id=callback_id,
                text="Estado actualizado",
            )
            self._show_status(message_id=message_id)
            return
        parts = data.split(":")
        action = parts[0]
        if action == "review_off":
            if len(parts) != 5:
                raise ValueError("invalid off review")
            token = _validated_token(parts[1])
            state = _state_from_parts(parts[2:])
            self._gateway.answer_callback(callback_query_id=callback_id)
            self._gateway.edit_message(
                chat_id=self._owner_user_id,
                message_id=message_id,
                text=_off_review_text(),
                reply_markup=_off_review_keyboard(token, state),
            )
            return

        if action in {"panel", "menu_fan", "menu_vane", "send_set", "cancel"}:
            if len(parts) != 5:
                raise ValueError("invalid control state")
            token = _validated_token(parts[1])
            state = _state_from_parts(parts[2:])
            if action == "send_set":
                self._send(
                    callback_id=callback_id,
                    message_id=message_id,
                    token=token,
                    command_type="set_state",
                    state_payload=state.as_command_payload(),
                )
                return
            self._gateway.answer_callback(callback_query_id=callback_id)
            if action in {"panel", "cancel"}:
                text = _panel_text(state)
                keyboard = _panel_keyboard(token, state)
            elif action == "menu_fan":
                text = _fan_menu_text(state)
                keyboard = _fan_menu_keyboard(token, state)
            else:
                text = _vane_menu_text(state)
                keyboard = _vane_menu_keyboard(token, state)
            self._gateway.edit_message(
                chat_id=self._owner_user_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
            )
            return
        if action == "confirm_off":
            if len(parts) != 2:
                raise ValueError("invalid off confirmation")
            self._send(
                callback_id=callback_id,
                message_id=message_id,
                token=_validated_token(parts[1]),
                command_type="power_off",
                state_payload=None,
            )
            return
        raise ValueError("unknown callback action")

    def _show_status(self, *, message_id: int | None = None) -> None:
        try:
            snapshot = self._status_provider() if self._status_provider is not None else None
        except (OSError, sqlite3.Error):
            snapshot = None
        text = (
            status_text(snapshot) if snapshot is not None else status_unavailable_text(__version__)
        )
        if message_id is None:
            self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=text,
                reply_markup=STATUS_KEYBOARD,
            )
            return
        self._gateway.edit_message(
            chat_id=self._owner_user_id,
            message_id=message_id,
            text=text,
            reply_markup=STATUS_KEYBOARD,
        )

    def _send(
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
                text="Enviando una única orden…",
            )
        self._gateway.edit_message(
            chat_id=self._owner_user_id,
            message_id=message_id,
            text="⏳ <b>Enviando ajuste a través de RUBIK…</b>",
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
                "⏱ <b>Límite de órdenes alcanzado</b>\n\n"
                f"Espera aproximadamente {error.retry_after_seconds} segundos y abre /ac de nuevo."
            )
        except (CommandConflictError, CommandInProgressError, DeviceBusyError):
            text = (
                "⏳ <b>Ya hay otra orden en curso</b>\n\n"
                "No se ha enviado una petición física adicional. Espera y abre /ac de nuevo."
            )
        except (OSError, sqlite3.Error):
            text = (
                "⚠️ <b>Resultado físico desconocido</b>\n\n"
                "RUBIK no ha podido registrar un resultado fiable. La orden podría haberse "
                "transmitido. No la repitas automáticamente; revisa Actividad en el dashboard."
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


def _state_data(prefix: str, token: str, state: PanelState) -> str:
    data = f"{prefix}:{token}:{state.temperature_c}:{state.fan.value}:{state.vertical_vane.value}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Telegram callback data exceeds 64 bytes")
    return data


def _idempotency_token(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def _validated_token(value: str) -> str:
    if len(value) != 20 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid confirmation token")
    return value


def _button(
    text: str,
    data: str,
    *,
    style: str | None = None,
) -> dict[str, str]:
    if not 1 <= len(data.encode("utf-8")) <= 64:
        raise ValueError("Telegram callback data must be from 1 through 64 bytes")
    button = {"text": text, "callback_data": data}
    if style is not None:
        button["style"] = style
    return button


def _panel_text(state: PanelState) -> str:
    return (
        "❄️ <b>AIRE ACONDICIONADO</b>\n\n"
        "<blockquote>Última configuración solicitada · No representa el estado físico "
        "actual</blockquote>\n\n"
        f"<b>{state.temperature_c} °C</b>\n"
        f"Frío · {_fan_label(state.fan)} · {_vane_label(state.vertical_vane)}\n\n"
        "Ajusta los valores y pulsa <b>Enviar ajuste</b>."
    )


def _panel_keyboard(token: str, state: PanelState) -> Mapping[str, object]:
    lower = PanelState(max(16, state.temperature_c - 1), state.fan, state.vertical_vane)
    higher = PanelState(min(31, state.temperature_c + 1), state.fan, state.vertical_vane)
    return {
        "inline_keyboard": [
            [
                _button("−", _state_data("panel", token, lower)),
                _button(f"{state.temperature_c} °C", "noop", style="primary"),
                _button("+", _state_data("panel", token, higher)),
            ],
            [
                _button(
                    f"💨 Ventilador · {_fan_label(state.fan)}",
                    _state_data("menu_fan", token, state),
                )
            ],
            [
                _button(
                    f"↕️ Lama · {_vane_label(state.vertical_vane)}",
                    _state_data("menu_vane", token, state),
                )
            ],
            [
                _button(
                    "Enviar ajuste",
                    _state_data("send_set", token, state),
                    style="success",
                )
            ],
            [
                _button(
                    "Apagar",
                    _state_data("review_off", token, state),
                    style="danger",
                )
            ],
        ]
    }


def _fan_menu_text(state: PanelState) -> str:
    return (
        "💨 <b>VELOCIDAD DEL VENTILADOR</b>\n\n"
        f"Seleccionado: <b>{_fan_label(state.fan)}</b>\n\n"
        "Elige una velocidad. Volverás automáticamente al mando."
    )


def _fan_menu_keyboard(token: str, state: PanelState) -> Mapping[str, object]:
    buttons = [
        _button(
            f"{'✓ ' if fan is state.fan else ''}{_fan_label(fan)}",
            _state_data(
                "panel",
                token,
                PanelState(state.temperature_c, fan, state.vertical_vane),
            ),
            style="primary" if fan is state.fan else None,
        )
        for fan in FANS
    ]
    return {
        "inline_keyboard": [
            buttons[:2],
            buttons[2:4],
            buttons[4:],
            [_button("‹ Volver", _state_data("panel", token, state))],
        ]
    }


def _vane_menu_text(state: PanelState) -> str:
    return (
        "↕️ <b>POSICIÓN DE LA LAMA</b>\n\n"
        f"Seleccionada: <b>{_vane_label(state.vertical_vane)}</b>\n\n"
        "Elige una posición. Volverás automáticamente al mando."
    )


def _vane_menu_keyboard(token: str, state: PanelState) -> Mapping[str, object]:
    buttons = [
        _button(
            f"{'✓ ' if vane is state.vertical_vane else ''}{_vane_label(vane)}",
            _state_data(
                "panel",
                token,
                PanelState(state.temperature_c, state.fan, vane),
            ),
            style="primary" if vane is state.vertical_vane else None,
        )
        for vane in VANES
    ]
    return {
        "inline_keyboard": [
            buttons[:2],
            buttons[2:4],
            buttons[4:6],
            buttons[6:],
            [_button("‹ Volver", _state_data("panel", token, state))],
        ]
    }


def _off_review_text() -> str:
    return (
        "⏻ <b>APAGAR AIRE ACONDICIONADO</b>\n\n"
        "Se enviará una única petición de apagado.\n\n"
        "El resultado registrado no confirma el estado físico del aparato."
    )


def _off_review_keyboard(
    token: str,
    fallback: PanelState | None = None,
) -> Mapping[str, object]:
    panel_state = fallback or PanelState()
    return {
        "inline_keyboard": [
            [
                _button("Cancelar", _state_data("cancel", token, panel_state)),
                _button("Confirmar apagado", f"confirm_off:{token}", style="danger"),
            ]
        ]
    }


def _result_text(execution: CommandExecution) -> str:
    outcome = execution.result.outcome
    replay_note = (
        "\nResultado recuperado de forma segura; no se ha repetido la petición."
        if execution.replayed
        else ""
    )
    if outcome is CommandOutcome.CONFIRMED_SUCCESS:
        heading = "✅ <b>ORDEN CONFIRMADA</b>"
        detail = "El controlador ha aceptado la petición."
    elif outcome is CommandOutcome.REJECTED_LOCALLY:
        heading = "⛔️ <b>ORDEN RECHAZADA LOCALMENTE</b>"
        detail = "RUBIK no ha contactado con el controlador."
    elif outcome is CommandOutcome.NODE_UNREACHABLE:
        heading = "📡 <b>CONTROLADOR NO DISPONIBLE</b>"
        detail = "No se ha confirmado una entrega correcta."
    elif outcome is CommandOutcome.NODE_REPORTED_FAILURE:
        heading = "❌ <b>EL CONTROLADOR HA RECHAZADO LA ORDEN</b>"
        detail = "El controlador no ha aceptado la petición."
    else:
        heading = "⚠️ <b>RESULTADO FÍSICO DESCONOCIDO</b>"
        detail = (
            "La petición podría haber llegado al controlador. No la repitas automáticamente; "
            "revisa Actividad en el dashboard."
        )
    return f"{heading}\n\n{detail}\nAuditoría #{execution.command_id}{replay_note}"


def _fan_label(fan: FanSpeed) -> str:
    return {
        FanSpeed.AUTO: "Auto",
        FanSpeed.LOW: "Bajo",
        FanSpeed.MEDIUM: "Medio",
        FanSpeed.HIGH: "Alto",
        FanSpeed.MAX: "Máximo",
    }[fan]


def _vane_label(vane: VerticalVane) -> str:
    return {
        VerticalVane.AUTO: "Auto",
        VerticalVane.HIGHEST: "Más alta",
        VerticalVane.HIGH: "Alta",
        VerticalVane.MIDDLE: "Centro",
        VerticalVane.LOW: "Baja",
        VerticalVane.LOWEST: "Más baja",
        VerticalVane.SWING: "Oscilar",
    }[vane]
