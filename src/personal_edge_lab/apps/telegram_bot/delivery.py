"""Telegram presentation and adapter for proactive operational notifications."""

from __future__ import annotations

from datetime import datetime
from html import escape

from personal_edge_lab.apps.telegram_bot.contracts import TelegramGateway
from personal_edge_lab.domain.alerting import AlertType
from personal_edge_lab.domain.notifications import (
    NotificationDelivery,
    NotificationEventType,
)
from personal_edge_lab.infrastructure.telegram.bot_api import TelegramApiError
from personal_edge_lab.modules.notifications import NotificationSendFailure

STATUS_BUTTON = {
    "inline_keyboard": [
        [
            {
                "text": "🧭 Ver estado",
                "callback_data": "status:open",
                "style": "primary",
            }
        ]
    ]
}


class TelegramNotificationSender:
    def __init__(self, *, gateway: TelegramGateway, owner_user_id: int) -> None:
        self._gateway = gateway
        self._owner_user_id = owner_user_id

    def send(self, delivery: NotificationDelivery) -> str | None:
        try:
            result = self._gateway.send_message(
                chat_id=self._owner_user_id,
                text=notification_text(delivery),
                reply_markup=STATUS_BUTTON,
            )
        except TelegramApiError as error:
            raise NotificationSendFailure(
                category=error.category,
                message=str(error),
                retry_after_seconds=error.retry_after_seconds,
            ) from error
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise NotificationSendFailure(
                category="invalid_response",
                message="Telegram returned an invalid sendMessage response",
            )
        return str(message_id)


def notification_text(delivery: NotificationDelivery) -> str:
    if delivery.coalesced_count >= 3:
        state = (
            "El último estado observado sigue siendo una incidencia activa."
            if delivery.event_type is NotificationEventType.OPERATIONAL_ALERT_STARTED
            else "El último estado observado indica que el componente se ha recuperado."
        )
        return (
            f"⚠️ <b>{_component_name(delivery.alert_type)} INESTABLE</b>\n\n"
            f"Ha cambiado de estado {delivery.coalesced_count} veces durante "
            f"los últimos 15 minutos.\n{state}\n\n"
            f"<i>{escape(delivery.device_id)}</i>"
        )

    if delivery.event_type is NotificationEventType.OPERATIONAL_ALERT_STARTED:
        duration = _duration(
            _payload_time(delivery, "suspect_started_at_utc"),
            delivery.occurred_at,
        )
        if delivery.alert_type is AlertType.TELEMETRY_STALE:
            detail = f"RUBIK no recibe muestras desde hace {duration}."
        else:
            detail = "El controlador acumula fallos de comunicación."
        return (
            f"⚠️ <b>{_started_title(delivery.alert_type)}</b>\n\n"
            f"{detail}\n\n"
            f"<i>{escape(delivery.device_id)}</i>"
        )

    recovered_at = _payload_time(delivery, "recovered_at_utc") or delivery.occurred_at
    alerting_at = _payload_time(delivery, "alerting_at_utc") or delivery.occurred_at
    duration = _duration(alerting_at, recovered_at)
    detail = (
        "RUBIK vuelve a recibir datos."
        if delivery.alert_type is AlertType.TELEMETRY_STALE
        else "El controlador vuelve a responder."
    )
    return (
        f"✅ <b>{_recovered_title(delivery.alert_type)}</b>\n\n"
        f"{detail}\nInterrupción: {duration}.\n\n"
        f"<i>{escape(delivery.device_id)}</i>"
    )


def _started_title(alert_type: AlertType) -> str:
    if alert_type is AlertType.TELEMETRY_STALE:
        return "TELEMETRÍA INTERRUMPIDA"
    return "ESP32 NO DISPONIBLE"


def _recovered_title(alert_type: AlertType) -> str:
    if alert_type is AlertType.TELEMETRY_STALE:
        return "TELEMETRÍA RECUPERADA"
    return "ESP32 RECUPERADO"


def _component_name(alert_type: AlertType) -> str:
    return "TELEMETRÍA" if alert_type is AlertType.TELEMETRY_STALE else "ESP32"


def _payload_time(delivery: NotificationDelivery, key: str) -> datetime | None:
    value = delivery.payload.get(key)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _duration(start: datetime | None, end: datetime) -> str:
    if start is None:
        return "un tiempo desconocido"
    seconds = max(0, round((end - start).total_seconds()))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, remaining_minutes = divmod(minutes, 60)
    if remaining_minutes:
        return f"{hours} h {remaining_minutes} min"
    return f"{hours} h"
