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
    CONCURRENCY_LIMITED = "concurrency_limited"


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
        queue_wait_seconds: float = 0,
        provider_elapsed_seconds: float | None = None,
        attempt_count: int = 1,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retry_eligible = retry_eligible
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.queue_wait_seconds = queue_wait_seconds
        self.provider_elapsed_seconds = provider_elapsed_seconds
        self.attempt_count = attempt_count

    def with_queue_wait(self, queue_wait_seconds: float) -> LanguageModelError:
        return LanguageModelError(
            str(self),
            category=self.category,
            retry_eligible=self.retry_eligible,
            http_status=self.http_status,
            retry_after_seconds=self.retry_after_seconds,
            queue_wait_seconds=self.queue_wait_seconds + queue_wait_seconds,
            provider_elapsed_seconds=self.provider_elapsed_seconds,
            attempt_count=self.attempt_count,
        )

    def with_provider_elapsed(self, provider_elapsed_seconds: float) -> LanguageModelError:
        return LanguageModelError(
            str(self),
            category=self.category,
            retry_eligible=self.retry_eligible,
            http_status=self.http_status,
            retry_after_seconds=self.retry_after_seconds,
            queue_wait_seconds=self.queue_wait_seconds,
            provider_elapsed_seconds=provider_elapsed_seconds,
            attempt_count=self.attempt_count,
        )


class LanguageModel(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResult: ...
