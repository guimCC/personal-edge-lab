"""Typed JSON response contracts for the local API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from personal_edge_lab.domain.ac import CommandAuditEntry, CommandOutcome
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.modules.telemetry import TelemetryHealth


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class TemperatureReadingResponse(ApiModel):
    device_id: str
    sensor: str
    received_at_utc: datetime
    estimated_sample_at_utc: datetime
    temperature_c: float
    raw_adc: int
    age_ms: int
    sample_interval_ms: int

    @classmethod
    def from_domain(cls, reading: TemperatureReading) -> TemperatureReadingResponse:
        return cls(
            device_id=reading.device_id,
            sensor=reading.sensor,
            received_at_utc=reading.received_at,
            estimated_sample_at_utc=reading.estimated_sample_at,
            temperature_c=reading.temperature_c,
            raw_adc=reading.raw_adc,
            age_ms=reading.age_ms,
            sample_interval_ms=reading.sample_interval_ms,
        )


class TemperatureHistoryResponse(ApiModel):
    count: int
    limit: int
    items: list[TemperatureReadingResponse]


class CommandAuditResponse(ApiModel):
    id: int
    device_id: str
    command_type: str
    command_payload: dict[str, JsonValue]
    requested_at_utc: datetime
    completed_at_utc: datetime | None
    outcome: CommandOutcome
    http_status: int | None
    response_body: str | None
    error_category: str | None
    error_message: str | None

    @classmethod
    def from_domain(cls, entry: CommandAuditEntry) -> CommandAuditResponse:
        payload = json.loads(entry.command_payload_json)
        if not isinstance(payload, dict):
            raise ValueError("stored command payload must be a JSON object")
        return cls(
            id=entry.id,
            device_id=entry.device_id,
            command_type=entry.command_type,
            command_payload=payload,
            requested_at_utc=entry.requested_at_utc,
            completed_at_utc=entry.completed_at_utc,
            outcome=entry.outcome,
            http_status=entry.http_status,
            response_body=entry.response_body,
            error_category=entry.error_category,
            error_message=entry.error_message,
        )


class CommandHistoryResponse(ApiModel):
    count: int
    limit: int
    items: list[CommandAuditResponse]


class DatabaseHealthResponse(ApiModel):
    status: Literal["healthy"] = "healthy"


class TelemetryHealthResponse(ApiModel):
    status: Literal["fresh", "stale", "no_data"]
    device_id: str
    last_received_at_utc: datetime | None
    age_seconds: float | None
    stale_after_seconds: float

    @classmethod
    def from_application(cls, health: TelemetryHealth) -> TelemetryHealthResponse:
        return cls(
            status=health.status.value,
            device_id=health.device_id,
            last_received_at_utc=health.last_received_at,
            age_seconds=health.age_seconds,
            stale_after_seconds=health.stale_after_seconds,
        )


class HealthResponse(ApiModel):
    status: Literal["healthy", "degraded"]
    version: str
    checked_at_utc: datetime
    database: DatabaseHealthResponse
    telemetry: TelemetryHealthResponse
