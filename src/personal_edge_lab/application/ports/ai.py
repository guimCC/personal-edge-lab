"""Application port for bounded language-model completion."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from personal_edge_lab.domain.ai import CompletionRequest, CompletionResult


class CompletionFailureCategory(StrEnum):
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    NOT_READY = "not_ready"
    REQUEST_REJECTED = "request_rejected"
    PROVIDER_FAILURE = "provider_failure"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"


class LanguageModelError(RuntimeError):
    """Sanitized language-model transport or protocol failure."""

    def __init__(
        self,
        message: str,
        *,
        category: CompletionFailureCategory,
        retry_eligible: bool,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retry_eligible = retry_eligible
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


class LanguageModel(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResult: ...
