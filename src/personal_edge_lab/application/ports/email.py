"""Application port for bounded, read-only email retrieval."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from personal_edge_lab.domain.email import EmailRetrievalBatch, EmailRetrievalRequest


class EmailSourceFailureCategory(StrEnum):
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    SOURCE_UNAVAILABLE = "source_unavailable"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"


class EmailSourceError(RuntimeError):
    """Sanitized email-source transport, authorization, or protocol failure."""

    def __init__(
        self,
        message: str,
        *,
        category: EmailSourceFailureCategory,
        retry_eligible: bool,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
        api_call_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retry_eligible = retry_eligible
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.api_call_count = api_call_count


class EmailSource(Protocol):
    def retrieve(self, request: EmailRetrievalRequest) -> EmailRetrievalBatch: ...
