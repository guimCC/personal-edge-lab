from __future__ import annotations

import pytest

from personal_edge_lab.domain.ai import (
    AiValidationError,
    CompletionRequest,
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
