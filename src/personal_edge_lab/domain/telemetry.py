"""Validated telemetry domain values."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


class ValidationError(ValueError):
    """Raised when a temperature payload violates the domain contract."""


@dataclass(frozen=True, slots=True)
class TemperatureReading:
    device_id: str
    sensor: str
    received_at: datetime
    estimated_sample_at: datetime
    temperature_c: float
    raw_adc: int
    age_ms: int
    sample_interval_ms: int

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        device_id: str,
        received_at: datetime | None = None,
    ) -> TemperatureReading:
        if not isinstance(payload, dict):
            raise ValidationError("response JSON must be an object")

        required = {"sensor", "temperature_c", "raw_adc", "age_ms", "sample_interval_ms"}
        missing = sorted(required - payload.keys())
        if missing:
            raise ValidationError(f"missing required fields: {', '.join(missing)}")

        sensor = payload["sensor"]
        if not isinstance(sensor, str) or not sensor.strip():
            raise ValidationError("sensor must be a non-empty string")

        temperature = payload["temperature_c"]
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ValidationError("temperature_c must be a number")
        temperature_c = float(temperature)
        if not math.isfinite(temperature_c) or not -100 <= temperature_c <= 200:
            raise ValidationError("temperature_c must be finite and between -100 and 200")

        raw_adc = _integer_field(payload, "raw_adc", minimum=0)
        age_ms = _integer_field(payload, "age_ms", minimum=0)
        sample_interval_ms = _integer_field(payload, "sample_interval_ms", minimum=1)

        timestamp = received_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValidationError("received_at must be timezone-aware")
        timestamp = timestamp.astimezone(UTC)

        return cls(
            device_id=device_id,
            sensor=sensor,
            received_at=timestamp,
            estimated_sample_at=timestamp - timedelta(milliseconds=age_ms),
            temperature_c=temperature_c,
            raw_adc=raw_adc,
            age_ms=age_ms,
            sample_interval_ms=sample_interval_ms,
        )


def _integer_field(payload: dict[str, Any], name: str, *, minimum: int) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")
    if value < minimum:
        raise ValidationError(f"{name} must be at least {minimum}")
    return value
