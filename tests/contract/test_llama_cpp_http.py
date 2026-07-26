from __future__ import annotations

import json

import httpx
import pytest

from personal_edge_lab.application.ports.ai import (
    CompletionFailureCategory,
    LanguageModelError,
)
from personal_edge_lab.domain.ai import CompletionRequest, ModelMessage, ModelRole
from personal_edge_lab.infrastructure.ai.llama_cpp import (
    LlamaCppHealthProbe,
    LlamaCppLanguageModel,
)

API_KEY = "never-log-this-api-key-value-123456"
SERVER_MODEL_PATH = "/home/arduino/models/Qwen3-1.7B-Q4_K_M.gguf"


def request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ModelMessage(ModelRole.USER, "Return exactly ready"),),
        model_alias="qwen3-1.7b-q4-k-m",
        max_output_tokens=32,
        temperature=0,
    )


def success_response(*, usage: object = ...):
    payload: dict[str, object] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": SERVER_MODEL_PATH,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ready"},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is ...:
        payload["usage"] = {
            "prompt_tokens": 5,
            "completion_tokens": 1,
            "total_tokens": 6,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
    elif usage is not None:
        payload["usage"] = usage
    return payload


def model(handler) -> LlamaCppLanguageModel:
    return LlamaCppLanguageModel(
        base_url="http://uno.local:8080",
        api_key=API_KEY,
        timeout_seconds=60,
        transport=httpx.MockTransport(handler),
    )


def test_success_sends_exact_bounded_request_and_translates_identity() -> None:
    calls = 0

    def handler(observed: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert observed.url == "http://uno.local:8080/v1/chat/completions"
        assert observed.headers["authorization"] == f"Bearer {API_KEY}"
        assert json.loads(observed.content) == {
            "model": "qwen3-1.7b-q4-k-m",
            "messages": [{"role": "user", "content": "Return exactly ready"}],
            "max_tokens": 32,
            "temperature": 0.0,
            "seed": 0,
            "stream": False,
        }
        return httpx.Response(200, json=success_response())

    with model(handler) as client:
        result = client.complete(request())

    assert calls == 1
    assert result.text == "ready"
    assert result.provider == "llama_cpp"
    assert result.model_alias == "qwen3-1.7b-q4-k-m"
    assert result.usage is not None
    assert result.usage.total_tokens == 6
    assert SERVER_MODEL_PATH not in repr(result)


def test_missing_usage_is_allowed() -> None:
    with model(lambda _: httpx.Response(200, json=success_response(usage=None))) as client:
        assert client.complete(request()).usage is None


@pytest.mark.parametrize(
    ("status", "category", "retry_eligible"),
    [
        (401, CompletionFailureCategory.AUTHENTICATION, False),
        (403, CompletionFailureCategory.AUTHENTICATION, False),
        (400, CompletionFailureCategory.REQUEST_REJECTED, False),
        (429, CompletionFailureCategory.RATE_LIMITED, True),
        (503, CompletionFailureCategory.NOT_READY, True),
        (500, CompletionFailureCategory.PROVIDER_FAILURE, True),
    ],
)
def test_http_failures_are_sanitized_and_categorized(
    status: int,
    category: CompletionFailureCategory,
    retry_eligible: bool,
) -> None:
    provider_secret = f"provider leaked {API_KEY}"
    headers = {"Retry-After": "17"} if status == 429 else {}
    with (
        model(
            lambda _: httpx.Response(
                status,
                json={"error": provider_secret},
                headers=headers,
            )
        ) as client,
        pytest.raises(LanguageModelError) as captured,
    ):
        client.complete(request())
    assert captured.value.category is category
    assert captured.value.retry_eligible is retry_eligible
    assert API_KEY not in str(captured.value)
    assert provider_secret not in str(captured.value)
    assert captured.value.retry_after_seconds == (17 if status == 429 else None)


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (httpx.ConnectError("offline"), CompletionFailureCategory.CONNECTION),
        (httpx.ReadTimeout("slow"), CompletionFailureCategory.TIMEOUT),
    ],
)
def test_transport_failures_are_categorized(
    exception: httpx.RequestError,
    category: CompletionFailureCategory,
) -> None:
    def handler(observed: httpx.Request) -> httpx.Response:
        exception.request = observed
        raise exception

    with model(handler) as client, pytest.raises(LanguageModelError) as captured:
        client.complete(request())
    assert captured.value.category is category
    assert captured.value.retry_eligible is True
    assert "uno.local" not in str(captured.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"[]",
        json.dumps({}).encode(),
        json.dumps({"choices": []}).encode(),
        json.dumps({"choices": [{}]}).encode(),
        json.dumps({"choices": [{"message": {}}]}).encode(),
        json.dumps(success_response(usage={})).encode(),
        json.dumps(
            success_response(usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 3})
        ).encode(),
        json.dumps(
            success_response(
                usage={"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2}
            )
        ).encode(),
    ],
)
def test_invalid_success_envelopes_are_rejected(payload: bytes) -> None:
    with (
        model(lambda _: httpx.Response(200, content=payload)) as client,
        pytest.raises(LanguageModelError) as captured,
    ):
        client.complete(request())
    assert captured.value.category is CompletionFailureCategory.INVALID_PROVIDER_RESPONSE


def test_client_closes_its_transport() -> None:
    class ClosingTransport(httpx.BaseTransport):
        closed = False

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=success_response(), request=request)

        def close(self) -> None:
            self.closed = True

    transport = ClosingTransport()
    with LlamaCppLanguageModel(
        base_url="http://uno.local:8080",
        api_key=API_KEY,
        timeout_seconds=60,
        transport=transport,
    ) as client:
        client.complete(request())
    assert transport.closed


def test_health_is_public_and_validates_minimal_response() -> None:
    def handler(observed: httpx.Request) -> httpx.Response:
        assert observed.url == "http://uno.local:8080/health"
        assert "authorization" not in observed.headers
        return httpx.Response(200, json={"status": "ok"})

    with LlamaCppHealthProbe(
        base_url="http://uno.local:8080",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    ) as probe:
        result = probe.check()
    assert result.status == "ok"
    assert result.provider == "llama_cpp"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": f"loading {API_KEY}"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"status": "loading", "model": SERVER_MODEL_PATH}),
    ],
)
def test_health_failures_are_sanitized(response: httpx.Response) -> None:
    with (
        LlamaCppHealthProbe(
            base_url="http://uno.local:8080",
            timeout_seconds=5,
            transport=httpx.MockTransport(lambda _: response),
        ) as probe,
        pytest.raises(LanguageModelError) as captured,
    ):
        probe.check()
    assert API_KEY not in str(captured.value)
    assert SERVER_MODEL_PATH not in str(captured.value)
