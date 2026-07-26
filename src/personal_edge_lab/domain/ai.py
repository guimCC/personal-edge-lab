"""Pure value types for bounded language-model inference."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

MAX_MESSAGE_COUNT = 16
MAX_TOTAL_INPUT_CHARS = 4096
MAX_OUTPUT_TOKENS = 256
MAX_MODEL_ALIAS_CHARS = 128
MODEL_ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class AiValidationError(ValueError):
    """Raised when a language-model request or result is invalid."""


class ModelRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: ModelRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, ModelRole):
            raise AiValidationError("message role is invalid")
        if not isinstance(self.content, str) or not self.content.strip():
            raise AiValidationError("message content must not be blank")
        if len(self.content) > MAX_TOTAL_INPUT_CHARS:
            raise AiValidationError(
                f"message content must not exceed {MAX_TOTAL_INPUT_CHARS} characters"
            )


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    messages: tuple[ModelMessage, ...]
    model_alias: str
    max_output_tokens: int
    temperature: float

    def __post_init__(self) -> None:
        if not isinstance(self.messages, tuple) or not self.messages:
            raise AiValidationError("at least one model message is required")
        if len(self.messages) > MAX_MESSAGE_COUNT:
            raise AiValidationError(f"at most {MAX_MESSAGE_COUNT} model messages are allowed")
        if not all(isinstance(message, ModelMessage) for message in self.messages):
            raise AiValidationError("messages must contain only ModelMessage values")
        if sum(len(message.content) for message in self.messages) > MAX_TOTAL_INPUT_CHARS:
            raise AiValidationError(
                f"total message content must not exceed {MAX_TOTAL_INPUT_CHARS} characters"
            )
        if (
            not isinstance(self.model_alias, str)
            or len(self.model_alias) > MAX_MODEL_ALIAS_CHARS
            or MODEL_ALIAS_PATTERN.fullmatch(self.model_alias) is None
        ):
            raise AiValidationError("model alias is invalid")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS
        ):
            raise AiValidationError(f"max output tokens must be from 1 through {MAX_OUTPUT_TOKENS}")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(float(self.temperature))
            or not 0 <= float(self.temperature) <= 2
        ):
            raise AiValidationError("temperature must be from 0 through 2")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        values = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values
        ):
            raise AiValidationError("token usage values must be non-negative integers")
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise AiValidationError("total token usage is inconsistent")


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    provider: str
    model_alias: str
    usage: TokenUsage | None
    elapsed_seconds: float
