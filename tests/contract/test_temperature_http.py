from __future__ import annotations

import httpx
import pytest

from personal_edge_lab.application.ports.telemetry import SourceFailureCategory
from personal_edge_lab.infrastructure.esp32.temperature_source import (
    EdgeNodeClient,
    TemperatureSourceError,
)


def make_client(handler: httpx.MockTransport) -> EdgeNodeClient:
    return EdgeNodeClient(
        url="http://node.local/temperature",
        device_id="node-1",
        timeout_seconds=1,
        transport=handler,
    )


def test_valid_temperature_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "sensor": "thermistor",
                "temperature_c": 24.31,
                "raw_adc": 1830,
                "age_ms": 420,
                "sample_interval_ms": 2000,
            },
        )
    )
    with make_client(transport) as client:
        reading = client.fetch_temperature()
    assert reading.device_id == "node-1"
    assert reading.temperature_c == 24.31
    assert reading.age_ms == 420


@pytest.mark.parametrize(
    "payload",
    [
        {"sensor": "thermistor"},
        {
            "sensor": "thermistor",
            "temperature_c": "hot",
            "raw_adc": 1830,
            "age_ms": 420,
            "sample_interval_ms": 2000,
        },
        {
            "sensor": "thermistor",
            "temperature_c": 24.0,
            "raw_adc": True,
            "age_ms": 420,
            "sample_interval_ms": 2000,
        },
    ],
)
def test_invalid_payloads(payload: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with make_client(transport) as client, pytest.raises(TemperatureSourceError, match="invalid"):
        client.fetch_temperature()


def test_non_200_response() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with (
        make_client(transport) as client,
        pytest.raises(TemperatureSourceError, match="503") as captured,
    ):
        client.fetch_temperature()
    assert captured.value.category is SourceFailureCategory.HTTP_STATUS


def test_invalid_json_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b"{not-json",
            headers={"content-type": "application/json"},
        )
    )
    with (
        make_client(transport) as client,
        pytest.raises(
            TemperatureSourceError,
            match="not valid JSON",
        ) as captured,
    ):
        client.fetch_temperature()
    assert captured.value.category is SourceFailureCategory.INVALID_JSON


@pytest.mark.parametrize("exception", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
def test_transport_failure(exception: httpx.RequestError) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise exception

    with (
        make_client(httpx.MockTransport(fail)) as client,
        pytest.raises(TemperatureSourceError) as captured,
    ):
        client.fetch_temperature()
    expected = (
        SourceFailureCategory.TIMEOUT
        if isinstance(exception, httpx.TimeoutException)
        else SourceFailureCategory.CONNECTION
    )
    assert captured.value.category is expected
    assert "node.local" not in str(captured.value)
