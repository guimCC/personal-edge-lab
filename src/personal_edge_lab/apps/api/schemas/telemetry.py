"""Telemetry response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from personal_edge_lab.apps.api.schemas.common import ApiModel
from personal_edge_lab.domain.telemetry import TemperatureReading
from personal_edge_lab.modules.telemetry import TelemetrySeries


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
            window=series.window.value,
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
