"""HTTP adapter for the current edge-node temperature contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from personal_edge_lab.application.ports.telemetry import (
    SourceFailureCategory,
    TemperatureSourceError,
)
from personal_edge_lab.domain.telemetry import TemperatureReading, ValidationError


class EdgeNodeClient:
    def __init__(
        self,
        *,
        url: str,
        device_id: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = url
        self._device_id = device_id
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def __enter__(self) -> EdgeNodeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_temperature(self) -> TemperatureReading:
        try:
            response = self._client.get(self._url)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            raise TemperatureSourceError(
                "temperature request timed out",
                category=SourceFailureCategory.TIMEOUT,
            ) from error
        except httpx.RequestError as error:
            raise TemperatureSourceError(
                "temperature node connection failed",
                category=SourceFailureCategory.CONNECTION,
            ) from error
        except httpx.HTTPStatusError as error:
            raise TemperatureSourceError(
                f"unexpected HTTP status {error.response.status_code}",
                category=SourceFailureCategory.HTTP_STATUS,
            ) from error
        except ValueError as error:
            raise TemperatureSourceError(
                "response body is not valid JSON",
                category=SourceFailureCategory.INVALID_JSON,
            ) from error

        received_at = datetime.now(UTC)
        try:
            return TemperatureReading.from_payload(
                payload,
                device_id=self._device_id,
                received_at=received_at,
            )
        except ValidationError as error:
            raise TemperatureSourceError(
                "invalid temperature response",
                category=SourceFailureCategory.INVALID_PAYLOAD,
            ) from error
