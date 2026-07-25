from __future__ import annotations

import json

import httpx
import pytest

from ac_control.client import MAX_RESPONSE_BODY_CHARS, AcCommandClient
from ac_control.models import AcState, CommandOutcome


def state() -> AcState:
    return AcState.from_values(
        power="on",
        temperature_c="24",
        mode="cool",
        fan="auto",
        vertical_vane="middle",
    )


def client(handler) -> AcCommandClient:
    return AcCommandClient(
        base_url="http://node.local",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def test_set_state_sends_exact_contract_and_accepts_exact_success() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        return httpx.Response(200, json={**payload, "state_source": "last_command"})

    with client(handler) as command_client:
        result = command_client.set_state(state())

    assert result.outcome is CommandOutcome.CONFIRMED_SUCCESS
    assert len(requests) == 1
    assert requests[0].method == "PUT"
    assert requests[0].url.path == "/ac/state"
    assert json.loads(requests[0].content) == state().as_payload()


def test_power_off_sends_one_post_and_accepts_exact_success() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "power": False})

    with client(handler) as command_client:
        result = command_client.power_off()

    assert result.outcome is CommandOutcome.CONFIRMED_SUCCESS
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/ac/off"


def test_non_200_is_node_reported_failure() -> None:
    with client(
        lambda request: httpx.Response(
            503,
            json={"error": "ac_controller_could_not_power_off"},
        )
    ) as command_client:
        result = command_client.power_off()

    assert result.outcome is CommandOutcome.NODE_REPORTED_FAILURE
    assert result.http_status == 503
    assert result.error_message == "ac_controller_could_not_power_off"


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ConnectError("DNS failure"),
        httpx.NetworkError("connection dropped"),
    ],
)
def test_connection_failure_is_node_unreachable(exception: httpx.RequestError) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with client(handler) as command_client:
        result = command_client.power_off()

    assert result.outcome is CommandOutcome.NODE_UNREACHABLE


def test_timeout_is_unknown_and_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with client(handler) as command_client:
        result = command_client.set_state(state())

    assert result.outcome is CommandOutcome.TIMEOUT_UNKNOWN
    assert calls == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"status": "ok"}),
        httpx.Response(
            200,
            json={
                "power": True,
                "mode": "cool",
                "temperature_c": 24,
                "fan": "auto",
                "vertical_vane": "middle",
                "state_source": "physical_state",
            },
        ),
    ],
)
def test_unexpected_200_response_has_unknown_outcome(response: httpx.Response) -> None:
    with client(lambda request: response) as command_client:
        result = command_client.set_state(state())

    assert result.outcome is CommandOutcome.RESPONSE_UNKNOWN
    assert result.error_category == "invalid_success_response"


def test_response_body_is_sanitized_and_truncated() -> None:
    body = "x" * (MAX_RESPONSE_BODY_CHARS + 100) + "\x00"
    with client(lambda request: httpx.Response(500, text=body)) as command_client:
        result = command_client.power_off()

    assert result.response_body is not None
    assert len(result.response_body) == MAX_RESPONSE_BODY_CHARS
    assert "\x00" not in result.response_body
