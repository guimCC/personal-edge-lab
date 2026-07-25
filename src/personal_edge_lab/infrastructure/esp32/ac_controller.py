"""Single-attempt HTTP adapter for the ESP32 AC command contract."""

from __future__ import annotations

from typing import Any

import httpx

from personal_edge_lab.domain.ac import AcState, CommandOutcome, CommandResult

MAX_RESPONSE_BODY_CHARS = 2048


class AcCommandClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        no_retry_transport = transport or httpx.HTTPTransport(retries=0)
        self._client = httpx.Client(timeout=timeout_seconds, transport=no_retry_transport)

    def __enter__(self) -> AcCommandClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def set_state(self, state: AcState) -> CommandResult:
        expected = {**state.as_payload(), "state_source": "last_command"}
        return self._request(
            "PUT",
            "/ac/state",
            expected_response=expected,
            json=state.as_payload(),
        )

    def power_off(self) -> CommandResult:
        return self._request(
            "POST",
            "/ac/off",
            expected_response={"status": "ok", "power": False},
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        expected_response: dict[str, object],
        **request_kwargs: Any,
    ) -> CommandResult:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{endpoint}",
                **request_kwargs,
            )
        except httpx.TimeoutException as error:
            return CommandResult(
                outcome=CommandOutcome.TIMEOUT_UNKNOWN,
                error_category="timeout",
                error_message=str(error) or "command request timed out",
            )
        except httpx.RequestError as error:
            return CommandResult(
                outcome=CommandOutcome.NODE_UNREACHABLE,
                error_category="transport_error",
                error_message=str(error) or "node could not be reached",
            )

        response_body = sanitize_response(response.text)
        if response.status_code != 200:
            return CommandResult(
                outcome=CommandOutcome.NODE_REPORTED_FAILURE,
                http_status=response.status_code,
                response_body=response_body,
                error_category="http_error",
                error_message=_response_error(response),
            )

        try:
            payload = response.json()
        except ValueError:
            payload = None
        if payload != expected_response:
            return CommandResult(
                outcome=CommandOutcome.RESPONSE_UNKNOWN,
                http_status=response.status_code,
                response_body=response_body,
                error_category="invalid_success_response",
                error_message="ESP32 returned an unexpected success response",
            )

        return CommandResult(
            outcome=CommandOutcome.CONFIRMED_SUCCESS,
            http_status=response.status_code,
            response_body=response_body,
        )


def sanitize_response(body: str) -> str:
    printable = "".join(
        character if character.isprintable() or character in "\r\n\t" else "�" for character in body
    )
    return printable[:MAX_RESPONSE_BODY_CHARS]


def _response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return sanitize_response(payload["error"])
    return f"ESP32 returned HTTP {response.status_code}"
