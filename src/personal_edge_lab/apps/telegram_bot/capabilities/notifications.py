"""Owner controls for proactive Telegram notification policy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from personal_edge_lab.apps.telegram_bot.contracts import (
    AuthorizedCallback,
    AuthorizedMessage,
    BotCommand,
    HomeAction,
    TelegramGateway,
)
from personal_edge_lab.domain.notifications import (
    NotificationOverview,
    NotificationPolicyMode,
)
from personal_edge_lab.modules.notifications import ManageNotificationPolicy

NOTIFICATIONS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "1 hora", "callback_data": "notifications:pause_1h"},
            {"text": "8 horas", "callback_data": "notifications:pause_8h"},
        ],
        [
            {
                "text": "Hasta mañana · 08:00",
                "callback_data": "notifications:pause_tomorrow",
            }
        ],
        [
            {
                "text": "Pausar indefinidamente",
                "callback_data": "notifications:pause_forever",
                "style": "danger",
            }
        ],
        [
            {
                "text": "↻ Actualizar",
                "callback_data": "notifications:refresh",
            }
        ],
    ]
}

PAUSED_KEYBOARD = {
    "inline_keyboard": [
        [
            {
                "text": "🔔 Reactivar",
                "callback_data": "notifications:resume",
                "style": "success",
            }
        ],
        [
            {
                "text": "🧭 Ver estado",
                "callback_data": "status:open",
                "style": "primary",
            }
        ],
    ]
}

RESUMED_KEYBOARD = {
    "inline_keyboard": [
        [
            {
                "text": "🧭 Ver estado actual",
                "callback_data": "status:open",
                "style": "primary",
            }
        ],
        [
            {
                "text": "Configurar notificaciones",
                "callback_data": "home:notifications",
            }
        ],
    ]
}


class NotificationsCapability:
    namespace = "notifications"
    commands = (BotCommand("notifications", "Configurar avisos operativos"),)
    home_action = HomeAction("🔔 Notificaciones")
    legacy_callback_actions = frozenset()

    def __init__(
        self,
        *,
        gateway: TelegramGateway,
        policy: ManageNotificationPolicy,
        owner_timezone: ZoneInfo,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._gateway = gateway
        self._policy = policy
        self._owner_timezone = owner_timezone
        self._clock = clock

    def handle_command(self, command: str, message: AuthorizedMessage) -> None:
        if command != "notifications":
            raise ValueError("unsupported notifications command")
        self._show(chat_id=message.chat_id)

    def open_from_home(self, callback: AuthorizedCallback) -> None:
        self._gateway.answer_callback(callback_query_id=callback.query_id)
        self._show(chat_id=callback.chat_id, message_id=callback.message_id)

    def handle_callback(self, action: str, callback: AuthorizedCallback) -> None:
        if action == "refresh":
            self._gateway.answer_callback(
                callback_query_id=callback.query_id,
                text="Configuración actualizada",
            )
            self._show(chat_id=callback.chat_id, message_id=callback.message_id)
            return
        if action == "pause_1h":
            self._policy.pause_for(timedelta(hours=1))
        elif action == "pause_8h":
            self._policy.pause_for(timedelta(hours=8))
        elif action == "pause_tomorrow":
            self._policy.pause_until(self._tomorrow_at_eight())
        elif action == "pause_forever":
            self._policy.pause_indefinitely()
        elif action == "resume":
            self._policy.resume()
            self._gateway.answer_callback(
                callback_query_id=callback.query_id,
                text="Notificaciones reactivadas",
            )
            self._gateway.edit_message(
                chat_id=callback.chat_id,
                message_id=callback.message_id,
                text=(
                    "🔔 <b>NOTIFICACIONES REACTIVADAS</b>\n\n"
                    "Las alertas anteriores no se enviarán ahora. "
                    "Casadaqui avisará de las nuevas transiciones operativas."
                ),
                reply_markup=RESUMED_KEYBOARD,
            )
            return
        else:
            raise ValueError("unknown notifications callback action")

        self._gateway.answer_callback(
            callback_query_id=callback.query_id,
            text="Notificaciones pausadas",
        )
        self._show(chat_id=callback.chat_id, message_id=callback.message_id)

    def _show(self, *, chat_id: int, message_id: int | None = None) -> None:
        overview = self._policy.get()
        text = notification_policy_text(overview, owner_timezone=self._owner_timezone)
        keyboard = (
            PAUSED_KEYBOARD
            if overview.policy.mode is not NotificationPolicyMode.ENABLED
            else NOTIFICATIONS_KEYBOARD
        )
        if message_id is None:
            self._gateway.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )
            return
        self._gateway.edit_message(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
        )

    def _tomorrow_at_eight(self) -> datetime:
        local_now = _aware(self._clock()).astimezone(self._owner_timezone)
        tomorrow = local_now.date() + timedelta(days=1)
        return datetime.combine(
            tomorrow,
            time(hour=8),
            tzinfo=self._owner_timezone,
        ).astimezone(UTC)


def notification_policy_text(
    overview: NotificationOverview,
    *,
    owner_timezone: ZoneInfo,
) -> str:
    policy = overview.policy
    if policy.mode is NotificationPolicyMode.ENABLED:
        pending = (
            ""
            if overview.pending_count == 0
            else f"\n\nEntregas pendientes: {overview.pending_count}."
        )
        return (
            "🔔 <b>NOTIFICACIONES OPERATIVAS</b>\n\n"
            "Estado: <b>activas</b>.\n"
            "Casadaqui avisará cuando una incidencia se confirme y cuando se recupere."
            f"{pending}"
        )
    if policy.mode is NotificationPolicyMode.PAUSED_INDEFINITELY:
        detail = "Pausadas <b>indefinidamente</b>."
    else:
        until = policy.paused_until
        detail = (
            "Pausadas temporalmente."
            if until is None
            else f"Pausadas hasta <b>{until.astimezone(owner_timezone):%d/%m · %H:%M}</b>."
        )
    return (
        "🔕 <b>NOTIFICACIONES OPERATIVAS</b>\n\n"
        f"{detail}\n\n"
        "El sistema continúa evaluando y registrando incidentes. "
        "Las alertas suprimidas no se enviarán al reactivar."
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("notifications clock must return a timezone-aware datetime")
    return value
