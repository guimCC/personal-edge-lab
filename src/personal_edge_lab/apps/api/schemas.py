"""Typed JSON response contracts for the local API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from personal_edge_lab.domain.ac import CommandAuditEntry, CommandOutcome
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.modules.telemetry import (
    CollectorHealth,
    EdgeNodeHealth,
    TelemetryHealth,
    TelemetrySeries,
)


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


class TemperatureBucketResponse(ApiModel):
    bucket_start_at_utc: datetime
    bucket_end_at_utc: datetime
    sample_count: int
    temperature_minimum_c: float | None
    temperature_average_c: float | None
    temperature_maximum_c: float | None


class TemperatureSeriesResponse(ApiModel):
    device_id: str
    window: Literal["1h", "6h", "24h"]
    start_at_utc: datetime
    end_at_utc: datetime
    bucket_seconds: int
    sample_count: int
    items: list[TemperatureBucketResponse]

    @classmethod
    def from_application(cls, series: TelemetrySeries) -> TemperatureSeriesResponse:
        return cls(
            device_id=series.device_id,
            window=series.window,
            start_at_utc=series.start_at,
            end_at_utc=series.end_at,
            bucket_seconds=series.bucket_seconds,
            sample_count=series.sample_count,
            items=[
                TemperatureBucketResponse(
                    bucket_start_at_utc=item.start_at,
                    bucket_end_at_utc=item.end_at,
                    sample_count=item.sample_count,
                    temperature_minimum_c=item.minimum_c,
                    temperature_average_c=item.average_c,
                    temperature_maximum_c=item.maximum_c,
                )
                for item in series.items
            ],
        )


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
    actor_id: str | None
    request_source: str
    idempotency_key: str | None

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
            actor_id=entry.actor_id,
            request_source=entry.request_source,
            idempotency_key=entry.idempotency_key,
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


class CollectorHealthResponse(ApiModel):
    status: Literal["running", "stopped", "stale", "no_data"]
    device_id: str
    process_started_at_utc: datetime | None
    heartbeat_at_utc: datetime | None
    heartbeat_age_seconds: float | None
    stale_after_seconds: float
    stopped_at_utc: datetime | None
    last_attempt_at_utc: datetime | None
    last_success_at_utc: datetime | None
    consecutive_failures: int

    @classmethod
    def from_application(cls, health: CollectorHealth) -> CollectorHealthResponse:
        return cls(
            status=health.status,
            device_id=health.device_id,
            process_started_at_utc=health.process_started_at,
            heartbeat_at_utc=health.heartbeat_at,
            heartbeat_age_seconds=health.heartbeat_age_seconds,
            stale_after_seconds=health.stale_after_seconds,
            stopped_at_utc=health.stopped_at,
            last_attempt_at_utc=health.last_attempt_at,
            last_success_at_utc=health.last_success_at,
            consecutive_failures=health.consecutive_failures,
        )


class EdgeNodeHealthResponse(ApiModel):
    status: Literal["reachable", "unreachable", "unknown"]
    device_id: str
    last_attempt_at_utc: datetime | None
    last_success_at_utc: datetime | None
    last_failure_at_utc: datetime | None
    last_failure_category: str | None
    last_failure_message: str | None

    @classmethod
    def from_application(cls, health: EdgeNodeHealth) -> EdgeNodeHealthResponse:
        return cls(
            status=health.status,
            device_id=health.device_id,
            last_attempt_at_utc=health.last_attempt_at,
            last_success_at_utc=health.last_success_at,
            last_failure_at_utc=health.last_failure_at,
            last_failure_category=health.last_failure_category,
            last_failure_message=health.last_failure_message,
        )


class HealthResponse(ApiModel):
    status: Literal["healthy", "degraded"]
    version: str
    checked_at_utc: datetime
    database: DatabaseHealthResponse
    telemetry: TelemetryHealthResponse
    collector: CollectorHealthResponse
    edge_node: EdgeNodeHealthResponse


class SessionResponse(ApiModel):
    authenticated: bool
    auth_enabled: bool
    controls_enabled: bool
    actor_id: str | None = None
    csrf_token: str | None = None
    idle_expires_at_utc: datetime | None = None
    absolute_expires_at_utc: datetime | None = None


class LoginRequest(ApiModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    password: str = Field(min_length=1)


class AcCommandRequest(ApiModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_type: str = Field(min_length=1)
    state: dict[str, JsonValue] | None = None


class AcCommandResponse(ApiModel):
    audit: CommandAuditResponse
    replayed: bool


class LivenessResponse(ApiModel):
    status: Literal["alive"] = "alive"
    version: str
