"""Authenticated adapter for the deployed llama.cpp OpenAI-compatible API."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import httpx

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.domain.ai import (
    AiValidationError,
    CompletionRequest,
    CompletionResult,
    TokenUsage,
)

PROVIDER_ID = "llama_cpp"


@dataclass(frozen=True, slots=True)
class LlamaCppHealthResult:
    status: str
    provider: str
    elapsed_seconds: float


class LlamaCppHealthProbe:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        no_retry_transport = transport or httpx.HTTPTransport(retries=0)
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=no_retry_transport,
        )

    def __enter__(self) -> LlamaCppHealthProbe:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def check(self) -> LlamaCppHealthResult:
        started = time.perf_counter()
        try:
            response = self._client.get("/health")
        except httpx.TimeoutException as error:
            raise _timeout_error() from error
        except httpx.RequestError as error:
            raise _connection_error() from error
        elapsed = time.perf_counter() - started
        if response.status_code != 200:
            raise _http_error(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise _invalid_response_error() from error
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise _invalid_response_error()
        return LlamaCppHealthResult(
            status="ok",
            provider=PROVIDER_ID,
            elapsed_seconds=elapsed,
        )


class LlamaCppLanguageModel:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        no_retry_transport = transport or httpx.HTTPTransport(retries=0)
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=no_retry_transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def __enter__(self) -> LlamaCppLanguageModel:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def complete(self, request: CompletionRequest) -> CompletionResult:
        payload = {
            "model": request.model_alias,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": float(request.temperature),
            "seed": 0,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            response = self._client.post("/v1/chat/completions", json=payload)
        except httpx.TimeoutException as error:
            raise _timeout_error() from error
        except httpx.RequestError as error:
            raise _connection_error() from error
        elapsed = time.perf_counter() - started
        if response.status_code != 200:
            raise _http_error(response)
        try:
            envelope = response.json()
        except ValueError as error:
            raise _invalid_response_error() from error
        text, usage = _parse_completion(envelope)
        return CompletionResult(
            text=text,
            provider=PROVIDER_ID,
            model_alias=request.model_alias,
            usage=usage,
            elapsed_seconds=elapsed,
        )


def _parse_completion(envelope: object) -> tuple[str, TokenUsage | None]:
    if not isinstance(envelope, dict):
        raise _invalid_response_error()
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise _invalid_response_error()
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise _invalid_response_error()
    return message["content"], _parse_usage(envelope.get("usage"))


def _parse_usage(value: object) -> TokenUsage | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _invalid_response_error()
    try:
        return TokenUsage(
            prompt_tokens=_usage_int(value, "prompt_tokens"),
            completion_tokens=_usage_int(value, "completion_tokens"),
            total_tokens=_usage_int(value, "total_tokens"),
        )
    except AiValidationError as error:
        raise _invalid_response_error() from error


def _usage_int(value: dict[str, Any], key: str) -> int:
    field = value.get(key)
    if isinstance(field, bool) or not isinstance(field, int):
        raise _invalid_response_error()
    return field


def _retry_after(response: httpx.Response) -> float | None:
    raw_value = response.headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _http_error(response: httpx.Response) -> LanguageModelError:
    status = response.status_code
    if status in {401, 403}:
        return LanguageModelError(
            "local language model authentication failed",
            category=CompletionFailureCategory.AUTHENTICATION,
            retry_eligible=False,
            http_status=status,
        )
    if status == 429:
        return LanguageModelError(
            "local language model rate limit reached",
            category=CompletionFailureCategory.RATE_LIMITED,
            retry_eligible=True,
            http_status=status,
            retry_after_seconds=_retry_after(response),
        )
    if status == 503:
        return LanguageModelError(
            "local language model is not ready",
            category=CompletionFailureCategory.NOT_READY,
            retry_eligible=True,
            http_status=status,
        )
    if 400 <= status < 500:
        return LanguageModelError(
            "local language model rejected the request",
            category=CompletionFailureCategory.REQUEST_REJECTED,
            retry_eligible=False,
            http_status=status,
        )
    return LanguageModelError(
        "local language model provider failed",
        category=CompletionFailureCategory.PROVIDER_FAILURE,
        retry_eligible=True,
        http_status=status,
    )


def _connection_error() -> LanguageModelError:
    return LanguageModelError(
        "local language model connection failed",
        category=CompletionFailureCategory.CONNECTION,
        retry_eligible=True,
    )


def _timeout_error() -> LanguageModelError:
    return LanguageModelError(
        "local language model request timed out",
        category=CompletionFailureCategory.TIMEOUT,
        retry_eligible=True,
    )


def _invalid_response_error() -> LanguageModelError:
    return LanguageModelError(
        "local language model returned an invalid response",
        category=CompletionFailureCategory.INVALID_PROVIDER_RESPONSE,
        retry_eligible=False,
    )
