from __future__ import annotations

import pytest

from personal_edge_lab.domain.ai import (
    AiValidationError,
    CompletionRequest,
    CompletionResult,
    CompletionTiming,
    ModelIdentity,
    ModelMessage,
    ModelRole,
    TokenUsage,
)


def message(content: str = "hello") -> ModelMessage:
    return ModelMessage(role=ModelRole.USER, content=content)


def request(**overrides: object) -> CompletionRequest:
    values = {
        "messages": (message(),),
        "model_alias": "qwen3-1.7b-q4-k-m",
        "max_output_tokens": 32,
        "temperature": 0,
        **overrides,
    }
    return CompletionRequest(**values)  # type: ignore[arg-type]


def test_valid_completion_request_and_usage() -> None:
    completion = request()
    usage = TokenUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6)
    assert completion.messages[0].role is ModelRole.USER
    assert usage.total_tokens == 6


def test_completion_result_exposes_stable_identity_and_timing_properties() -> None:
    result = CompletionResult(
        text="",
        identity=ModelIdentity(provider="llama_cpp", model_alias="qwen3-1.7b-q4-k-m"),
        usage=None,
        timing=CompletionTiming(queue_wait_seconds=1.25, provider_seconds=2.75),
    )
    assert result.text == ""
    assert result.provider == "llama_cpp"
    assert result.model_alias == "qwen3-1.7b-q4-k-m"
    assert result.elapsed_seconds == 4


@pytest.mark.parametrize(
    "content",
    ["", "   ", "x" * 4097],
)
def test_invalid_message_content_is_rejected(content: str) -> None:
    with pytest.raises(AiValidationError):
        message(content)


def test_message_role_must_be_typed() -> None:
    with pytest.raises(AiValidationError, match="role"):
        ModelMessage(role="user", content="hello")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message_text"),
    [
        ({"messages": ()}, "at least one"),
        ({"messages": tuple(message() for _ in range(17))}, "at most 16"),
        ({"messages": (message("x" * 2048), message("y" * 2049))}, "4096"),
        ({"model_alias": "GGUF path"}, "model alias"),
        ({"model_alias": "x" * 129}, "model alias"),
        ({"max_output_tokens": 0}, "1 through 256"),
        ({"max_output_tokens": 257}, "1 through 256"),
        ({"temperature": -0.1}, "0 through 2"),
        ({"temperature": 2.1}, "0 through 2"),
    ],
)
def test_invalid_completion_requests_are_rejected(
    overrides: dict[str, object],
    message_text: str,
) -> None:
    with pytest.raises(AiValidationError, match=message_text):
        request(**overrides)


@pytest.mark.parametrize(
    "values",
    [
        (-1, 1, 0),
        (True, 1, 2),
        (1, 1, 3),
    ],
)
def test_invalid_token_usage_is_rejected(values: tuple[object, object, object]) -> None:
    with pytest.raises(AiValidationError):
        TokenUsage(*values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("provider", "model_alias"),
    [
        ("Llama CPP", "qwen3"),
        ("llama_cpp", "GGUF path"),
        ("x" * 65, "qwen3"),
        ("llama_cpp", "x" * 129),
    ],
)
def test_invalid_model_identity_is_rejected(provider: str, model_alias: str) -> None:
    with pytest.raises(AiValidationError):
        ModelIdentity(provider=provider, model_alias=model_alias)


@pytest.mark.parametrize(
    ("queue_wait", "provider"),
    [
        (-1, 0),
        (0, -1),
        (float("nan"), 0),
        (0, float("inf")),
        (True, 0),
    ],
)
def test_invalid_completion_timing_is_rejected(queue_wait: object, provider: object) -> None:
    with pytest.raises(AiValidationError):
        CompletionTiming(  # type: ignore[arg-type]
            queue_wait_seconds=queue_wait,
            provider_seconds=provider,
        )


def test_completion_result_requires_typed_values() -> None:
    identity = ModelIdentity(provider="llama_cpp", model_alias="qwen3")
    timing = CompletionTiming(queue_wait_seconds=0, provider_seconds=1)
    with pytest.raises(AiValidationError, match="text"):
        CompletionResult(text=None, identity=identity, usage=None, timing=timing)  # type: ignore[arg-type]
    with pytest.raises(AiValidationError, match="identity"):
        CompletionResult(text="", identity=None, usage=None, timing=timing)  # type: ignore[arg-type]
    with pytest.raises(AiValidationError, match="usage"):
        CompletionResult(text="", identity=identity, usage="bad", timing=timing)  # type: ignore[arg-type]
    with pytest.raises(AiValidationError, match="timing"):
        CompletionResult(text="", identity=identity, usage=None, timing=None)  # type: ignore[arg-type]
