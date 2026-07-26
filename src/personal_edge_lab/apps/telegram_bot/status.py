"""Telegram presentation of the shared platform-health model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

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
                "callback_data": "refresh_status",
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


def status_text(snapshot: TelegramStatusSnapshot) -> str:
    health = snapshot.platform
    overall_healthy = snapshot.api_reachable and health.status is PlatformHealthStatus.HEALTHY
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
        "✅ <b>Telegram</b> · conectado",
        "",
        f"{overall_icon} <b>Estado general · {overall_label}</b>",
        f"Versión {snapshot.version} · {_utc_label(health.checked_at)}",
    ]
    return "\n".join(lines)


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
        return f"✅ <b>Colector</b> · activo · pulso {age}"
    if status is CollectorHealthStatus.STOPPED:
        return f"⏹ <b>Colector</b> · detenido · último pulso {age}"
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
        return (
            "✅ <b>ESP32</b> · accesible · éxito "
            f"{_age_label(_seconds_since(last_success_at, checked_at))}"
        )
    if status is EdgeNodeHealthStatus.UNREACHABLE:
        return (
            "❌ <b>ESP32</b> · no disponible · intento "
            f"{_age_label(_seconds_since(last_attempt_at, checked_at))}"
        )
    if last_success_at is not None:
        return (
            "❔ <b>ESP32</b> · estado desconocido · último éxito "
            f"{_age_label(_seconds_since(last_success_at, checked_at))}"
        )
    return "❔ <b>ESP32</b> · estado desconocido"


def _telemetry_line(status: TelemetryFreshness, age_seconds: float | None) -> str:
    if status is TelemetryFreshness.FRESH:
        return f"✅ <b>Telemetría</b> · fresca · muestra {_age_label(age_seconds)}"
    if status is TelemetryFreshness.STALE:
        return f"⚠️ <b>Telemetría</b> · atrasada · muestra {_age_label(age_seconds)}"
    return "❔ <b>Telemetría</b> · sin datos"


def _alerts_line(
    status: AlertStatusSummary,
    *,
    active_count: int,
    evaluator_age_seconds: float | None,
) -> str:
    evaluated = _age_label(evaluator_age_seconds)
    if status is AlertStatusSummary.HEALTHY:
        return f"✅ <b>Alertas</b> · normal · evaluación {evaluated}"
    if status is AlertStatusSummary.RECOVERED:
        return f"✅ <b>Alertas</b> · recuperadas · evaluación {evaluated}"
    if status is AlertStatusSummary.SUSPECT:
        return f"⚠️ <b>Alertas</b> · observando · evaluación {evaluated}"
    if status is AlertStatusSummary.ALERTING:
        noun = "incidencia activa" if active_count == 1 else "incidencias activas"
        return f"❌ <b>Alertas</b> · {active_count} {noun} · evaluación {evaluated}"
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
        return "ahora"
    if seconds < 60:
        return f"hace {seconds} s"
    minutes, _remaining_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"hace {minutes} min"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"hace {hours} h {remaining_minutes} min"
    days = hours // 24
    return f"hace {days} d"


def _utc_label(value: datetime) -> str:
    return f"{value:%H:%M:%S} UTC"
