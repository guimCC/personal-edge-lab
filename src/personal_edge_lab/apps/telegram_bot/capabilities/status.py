"""Owner-authorized Telegram capability for shared platform health."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

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
    NotificationRuntimeOutcome,
)
from personal_edge_lab.modules.alerting import AlertStatusSummary
from personal_edge_lab.modules.platform_status import PlatformHealth, PlatformHealthStatus
from personal_edge_lab.modules.telemetry import (
    CollectorHealthStatus,
    EdgeNodeHealthStatus,
    TelemetryFreshness,
)

STATUS_KEYBOARD: Final = {
    "inline_keyboard": [
        [
            {
                "text": "↻ Actualizar",
                "callback_data": "status:refresh",
                "style": "primary",
            }
        ]
    ]
}


@dataclass(frozen=True, slots=True)
class TelegramStatusSnapshot:
    platform: PlatformHealth
    api_reachable: bool
    version: str
    notifications: NotificationOverview | None = None
    notifications_enabled: bool = False
    notification_runtime_stale_after_seconds: float = 90


StatusProvider = Callable[[], TelegramStatusSnapshot]


class StatusCapability:
    namespace = "status"
    commands = (BotCommand("status", "Ver el estado de RUBIK"),)
    home_action = HomeAction("🧭 Estado")
    legacy_callback_actions = frozenset({"refresh_status"})

    def __init__(
        self,
        *,
        gateway: TelegramGateway,
        status_provider: StatusProvider,
        version: str,
    ) -> None:
        self._gateway = gateway
        self._status_provider = status_provider
        self._version = version

    def handle_command(self, command: str, message: AuthorizedMessage) -> None:
        if command != "status":
            raise ValueError("unsupported status command")
        self._show(chat_id=message.chat_id)

    def open_from_home(self, callback: AuthorizedCallback) -> None:
        self._gateway.answer_callback(callback_query_id=callback.query_id)
        self._show(
            chat_id=callback.chat_id,
            message_id=callback.message_id,
        )

    def handle_callback(self, action: str, callback: AuthorizedCallback) -> None:
        if action == "open":
            self._gateway.answer_callback(callback_query_id=callback.query_id)
            self._show(chat_id=callback.chat_id)
            return
        if action not in {"refresh", "refresh_status"}:
            raise ValueError("unknown status callback action")
        self._gateway.answer_callback(
            callback_query_id=callback.query_id,
            text="Estado actualizado",
        )
        self._show(
            chat_id=callback.chat_id,
            message_id=callback.message_id,
        )

    def _show(self, *, chat_id: int, message_id: int | None = None) -> None:
        try:
            snapshot = self._status_provider()
        except (OSError, sqlite3.Error):
            snapshot = None
        text = (
            status_text(snapshot)
            if snapshot is not None
            else status_unavailable_text(self._version)
        )
        if message_id is None:
            self._gateway.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=STATUS_KEYBOARD,
            )
            return
        self._gateway.edit_message(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=STATUS_KEYBOARD,
        )


def status_text(snapshot: TelegramStatusSnapshot) -> str:
    health = snapshot.platform
    notifications_healthy = _notifications_healthy(snapshot, checked_at=health.checked_at)
    overall_healthy = (
        snapshot.api_reachable
        and health.status is PlatformHealthStatus.HEALTHY
        and notifications_healthy
    )
    overall_icon = "✅" if overall_healthy else "⚠️"
    overall_label = "OPERATIVO" if overall_healthy else "DEGRADADO"
    lines = [
        "🧭 <b>PERSONAL EDGE LAB</b>",
        "<blockquote>Estado observado desde RUBIK</blockquote>",
        "",
        _api_line(snapshot.api_reachable),
        _collector_line(health.collector.status, health.collector.heartbeat_age_seconds),
        _edge_line(
            health.edge_node.status,
            health.edge_node.last_attempt_at,
            health.edge_node.last_success_at,
            checked_at=health.checked_at,
        ),
        _telemetry_line(health.telemetry.status, health.telemetry.age_seconds),
        _alerts_line(
            health.alerts.status,
            active_count=health.alerts.active_count,
            evaluator_age_seconds=health.alerts.evaluator_age_seconds,
        ),
        _notifications_line(snapshot, checked_at=health.checked_at),
        "✅ <b>Telegram</b> · conectado",
        "",
        f"{overall_icon} <b>Estado general · {overall_label}</b>",
        f"Versión {snapshot.version} · {_utc_label(health.checked_at)}",
    ]
    return "\n".join(lines)


def _notifications_healthy(
    snapshot: TelegramStatusSnapshot,
    *,
    checked_at: datetime,
) -> bool:
    if not snapshot.notifications_enabled:
        return True
    overview = snapshot.notifications
    if overview is None or overview.policy.is_paused(checked_at):
        return True
    runtime = overview.runtime
    if (
        runtime is None
        or runtime.last_finished_at is None
        or runtime.last_outcome is not NotificationRuntimeOutcome.SUCCESS
        or overview.failed_pending_count > 0
    ):
        return False
    return (
        checked_at - runtime.last_finished_at
    ).total_seconds() <= snapshot.notification_runtime_stale_after_seconds


def _notifications_line(
    snapshot: TelegramStatusSnapshot,
    *,
    checked_at: datetime,
) -> str:
    if not snapshot.notifications_enabled:
        return "⏸ <b>Notificaciones</b> · entrega desactivada"
    overview = snapshot.notifications
    if overview is None:
        return "❔ <b>Notificaciones</b> · estado desconocido"
    policy = overview.policy
    if policy.mode is NotificationPolicyMode.PAUSED_INDEFINITELY:
        return "🔕 <b>Notificaciones</b> · pausadas indefinidamente"
    if policy.is_paused(checked_at):
        remaining = (
            None
            if policy.paused_until is None
            else max(0.0, (policy.paused_until - checked_at).total_seconds())
        )
        return f"🔕 <b>Notificaciones</b> · pausadas · {_age_label(remaining)}"
    if not _notifications_healthy(snapshot, checked_at=checked_at):
        return "⚠️ <b>Notificaciones</b> · entrega degradada"
    if overview.pending_count:
        return f"⏳ <b>Notificaciones</b> · {overview.pending_count} pendientes"
    return "✅ <b>Notificaciones</b> · operativas"


def status_unavailable_text(version: str) -> str:
    return (
        "⚠️ <b>ESTADO NO DISPONIBLE</b>\n\n"
        "RUBIK no ha podido consultar sus datos operativos ahora mismo. "
        "No se ha enviado ninguna orden al aire acondicionado.\n\n"
        f"Versión {version}"
    )


def _api_line(reachable: bool) -> str:
    if reachable:
        return "✅ <b>API</b> · disponible"
    return "⚠️ <b>API</b> · no responde en RUBIK"


def _collector_line(status: CollectorHealthStatus, age_seconds: float | None) -> str:
    age = _age_label(age_seconds)
    if status is CollectorHealthStatus.RUNNING:
        return f"✅ <b>Colector</b> · activo · {age}"
    if status is CollectorHealthStatus.STOPPED:
        return f"⏹ <b>Colector</b> · detenido · {age}"
    if status is CollectorHealthStatus.STALE:
        return f"⚠️ <b>Colector</b> · sin pulso reciente · {age}"
    return "❔ <b>Colector</b> · sin datos"


def _edge_line(
    status: EdgeNodeHealthStatus,
    last_attempt_at: datetime | None,
    last_success_at: datetime | None,
    *,
    checked_at: datetime,
) -> str:
    if status is EdgeNodeHealthStatus.REACHABLE:
        age = _age_label(_seconds_since(last_success_at, checked_at))
        return f"✅ <b>ESP32</b> · accesible · {age}"
    if status is EdgeNodeHealthStatus.UNREACHABLE:
        age = _age_label(_seconds_since(last_attempt_at, checked_at))
        return f"❌ <b>ESP32</b> · no disponible · {age}"
    if last_success_at is not None:
        age = _age_label(_seconds_since(last_success_at, checked_at))
        return f"❔ <b>ESP32</b> · estado desconocido · {age}"
    return "❔ <b>ESP32</b> · estado desconocido"


def _telemetry_line(status: TelemetryFreshness, age_seconds: float | None) -> str:
    if status is TelemetryFreshness.FRESH:
        return f"✅ <b>Telemetría</b> · fresca · {_age_label(age_seconds)}"
    if status is TelemetryFreshness.STALE:
        return f"⚠️ <b>Telemetría</b> · atrasada · {_age_label(age_seconds)}"
    return "❔ <b>Telemetría</b> · sin datos"


def _alerts_line(
    status: AlertStatusSummary,
    *,
    active_count: int,
    evaluator_age_seconds: float | None,
) -> str:
    evaluated = _age_label(evaluator_age_seconds)
    if status is AlertStatusSummary.HEALTHY:
        return f"✅ <b>Alertas</b> · normal · {evaluated}"
    if status is AlertStatusSummary.RECOVERED:
        return f"✅ <b>Alertas</b> · recuperadas · {evaluated}"
    if status is AlertStatusSummary.SUSPECT:
        return f"⚠️ <b>Alertas</b> · observando · {evaluated}"
    if status is AlertStatusSummary.ALERTING:
        noun = "incidencia activa" if active_count == 1 else "incidencias activas"
        return f"❌ <b>Alertas</b> · {active_count} {noun} · {evaluated}"
    return "❔ <b>Alertas</b> · evaluación desconocida"


def _seconds_since(value: datetime | None, checked_at: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (checked_at - value).total_seconds())


def _age_label(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "desconocido"
    seconds = max(0, round(age_seconds))
    if seconds < 1:
        return "0 s"
    if seconds < 60:
        return f"{seconds} s"
    minutes, _remaining_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {remaining_minutes} min"
    days = hours // 24
    return f"{days} d"


def _utc_label(value: datetime) -> str:
    return f"{value:%H:%M:%S} UTC"
