"""Validated AC states, command outcomes, and audit records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ValidationError(ValueError):
    """Raised when a high-level AC command is invalid."""


class AcMode(StrEnum):
    AUTO = "auto"
    COOL = "cool"
    HEAT = "heat"
    DRY = "dry"
    FAN = "fan"


class FanSpeed(StrEnum):
    AUTO = "auto"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class VerticalVane(StrEnum):
    AUTO = "auto"
    HIGHEST = "highest"
    HIGH = "high"
    MIDDLE = "middle"
    LOW = "low"
    LOWEST = "lowest"
    SWING = "swing"


class CommandOutcome(StrEnum):
    PENDING = "pending"
    CONFIRMED_SUCCESS = "confirmed_success"
    REJECTED_LOCALLY = "rejected_locally"
    NODE_UNREACHABLE = "node_unreachable"
    TIMEOUT_UNKNOWN = "timeout_unknown"
    NODE_REPORTED_FAILURE = "node_reported_failure"
    RESPONSE_UNKNOWN = "response_unknown"


class CommandReservationStatus(StrEnum):
    NEW = "new"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"
    CONFLICT = "conflict"
    DEVICE_BUSY = "device_busy"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class CommandRequestContext:
    actor_id: str
    request_source: str
    idempotency_key: str
    rate_limit: int
    rate_window_seconds: int
    lock_lease_seconds: float


@dataclass(frozen=True, slots=True)
class AcState:
    power: bool
    temperature_c: int
    mode: AcMode
    fan: FanSpeed
    vertical_vane: VerticalVane

    @classmethod
    def from_values(
        cls,
        *,
        power: object,
        temperature_c: object,
        mode: object,
        fan: object,
        vertical_vane: object,
    ) -> AcState:
        missing = [
            name
            for name, value in {
                "power": power,
                "temperature": temperature_c,
                "mode": mode,
                "fan": fan,
                "vertical-vane": vertical_vane,
            }.items()
            if value is None
        ]
        if missing:
            raise ValidationError(f"missing required fields: {', '.join(missing)}")

        if power not in {"on", "off", True, False}:
            raise ValidationError("power must be 'on' or 'off'")
        normalized_power = power in {"on", True}

        if isinstance(temperature_c, bool):
            raise ValidationError("temperature must be an integer from 16 through 31")
        try:
            normalized_temperature = int(str(temperature_c))
        except (TypeError, ValueError) as error:
            raise ValidationError("temperature must be an integer from 16 through 31") from error
        is_exact_integer = str(normalized_temperature) == str(temperature_c)
        if not is_exact_integer or not 16 <= normalized_temperature <= 31:
            raise ValidationError("temperature must be an integer from 16 through 31")

        return cls(
            power=normalized_power,
            temperature_c=normalized_temperature,
            mode=_enum_value(AcMode, mode, "mode"),
            fan=_enum_value(FanSpeed, fan, "fan"),
            vertical_vane=_enum_value(VerticalVane, vertical_vane, "vertical-vane"),
        )

    def as_payload(self) -> dict[str, bool | int | str]:
        return {
            "power": self.power,
            "mode": self.mode.value,
            "temperature_c": self.temperature_c,
            "fan": self.fan.value,
            "vertical_vane": self.vertical_vane.value,
        }

    def to_json(self) -> str:
        return canonical_json(self.as_payload())


@dataclass(frozen=True, slots=True)
class CommandResult:
    outcome: CommandOutcome
    http_status: int | None = None
    response_body: str | None = None
    error_category: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class CommandExecution:
    command_id: int
    command_type: str
    payload_json: str
    result: CommandResult
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CommandAuditEntry:
    id: int
    device_id: str
    command_type: str
    command_payload_json: str
    requested_at_utc: datetime
    completed_at_utc: datetime | None
    outcome: CommandOutcome
    http_status: int | None
    response_body: str | None
    error_category: str | None
    error_message: str | None
    actor_id: str | None = None
    request_source: str = "local_cli"
    idempotency_key: str | None = None
    request_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class CommandReservation:
    status: CommandReservationStatus
    command_id: int | None = None
    entry: CommandAuditEntry | None = None
    retry_after_seconds: int | None = None


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _enum_value(enum_type: type[StrEnum], value: object, field_name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        supported = ", ".join(item.value for item in enum_type)
        raise ValidationError(f"{field_name} must be one of: {supported}") from error
