"""AC audit and command contracts."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import ConfigDict, Field, JsonValue

from personal_edge_lab.apps.api.schemas.common import ApiModel, StoredDataError
from personal_edge_lab.domain.ac import CommandAuditEntry, CommandOutcome


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
        try:
            payload = json.loads(entry.command_payload_json)
        except json.JSONDecodeError as error:
            raise StoredDataError("stored command payload is invalid") from error
        if not isinstance(payload, dict):
            raise StoredDataError("stored command payload is not an object")
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


class AcCommandRequest(ApiModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_type: str = Field(min_length=1)
    state: dict[str, JsonValue] | None = None


class AcCommandResponse(ApiModel):
    audit: CommandAuditResponse
    replayed: bool
