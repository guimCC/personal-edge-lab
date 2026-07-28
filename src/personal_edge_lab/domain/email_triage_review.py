"""Pure contracts for protected, read-only triage review."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from personal_edge_lab.domain.email import EmailContentSource, EmailMessageId
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_runs import TriageRunItemStatus

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TriageReviewValidationError(ValueError):
    """Raised when review evidence violates its bounded contract."""


class TriageRunFilter(StrEnum):
    ALL = "all"
    COMPLETED = "completed"
    ISSUES = "issues"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class TriageReviewReference:
    run_id: str
    ordinal: int
    message_id: EmailMessageId | None
    message_fingerprint: str
    item_status: TriageRunItemStatus
    label: TriageLabel | None
    normalized_sha256: str | None
    model_input_sha256: str | None
    model_message_chars: int | None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise TriageReviewValidationError("triage review run ID is invalid")
        if isinstance(self.ordinal, bool) or not 1 <= self.ordinal <= 10:
            raise TriageReviewValidationError("triage review ordinal is invalid")
        if self.message_id is not None and not isinstance(self.message_id, EmailMessageId):
            raise TriageReviewValidationError("triage review message ID is invalid")
        if HASH_PATTERN.fullmatch(self.message_fingerprint) is None:
            raise TriageReviewValidationError("triage review fingerprint is invalid")
        if not isinstance(self.item_status, TriageRunItemStatus):
            raise TriageReviewValidationError("triage review item status is invalid")
        if self.label is not None and not isinstance(self.label, TriageLabel):
            raise TriageReviewValidationError("triage review label is invalid")
        hashes = (self.normalized_sha256, self.model_input_sha256)
        if any(value is not None and HASH_PATTERN.fullmatch(value) is None for value in hashes):
            raise TriageReviewValidationError("triage review content hash is invalid")
        if self.model_message_chars is not None and (
            isinstance(self.model_message_chars, bool) or not 0 <= self.model_message_chars <= 1600
        ):
            raise TriageReviewValidationError("triage review model-input length is invalid")


@dataclass(frozen=True, slots=True)
class TriageReviewContent:
    run_id: str
    ordinal: int
    message_fingerprint: str
    sender: str
    subject: str
    model_input: str
    normalized_remainder: str
    normalized_chars: int
    model_input_chars: int
    content_source: EmailContentSource
    cleanup_flags: tuple[str, ...]
    source_truncated: bool
    model_input_truncated: bool
    metadata_truncated: bool
    identity_verified: bool
    elapsed_seconds: float
    api_call_count: int

    def __post_init__(self) -> None:
        if not self.run_id or not self.message_fingerprint:
            raise TriageReviewValidationError("triage review content identity is invalid")
        if isinstance(self.ordinal, bool) or not 1 <= self.ordinal <= 10:
            raise TriageReviewValidationError("triage review content ordinal is invalid")
        if not self.sender.strip():
            raise TriageReviewValidationError("triage review sender is invalid")
        if self.model_input_chars != len(self.model_input):
            raise TriageReviewValidationError("triage review model-input length is inconsistent")
        if self.normalized_chars != len(self.model_input) + len(self.normalized_remainder):
            raise TriageReviewValidationError("triage review normalized length is inconsistent")
        if self.model_input_chars > 1600:
            raise TriageReviewValidationError("triage review model input is too large")
        if not isinstance(self.content_source, EmailContentSource):
            raise TriageReviewValidationError("triage review content source is invalid")
        if not all(isinstance(flag, str) and flag for flag in self.cleanup_flags):
            raise TriageReviewValidationError("triage review cleanup flags are invalid")
        flags = (
            self.source_truncated,
            self.model_input_truncated,
            self.metadata_truncated,
            self.identity_verified,
        )
        if not all(isinstance(flag, bool) for flag in flags):
            raise TriageReviewValidationError("triage review flags are invalid")
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or not math.isfinite(float(self.elapsed_seconds))
            or self.elapsed_seconds < 0
        ):
            raise TriageReviewValidationError("triage review elapsed time is invalid")
        if isinstance(self.api_call_count, bool) or self.api_call_count != 1:
            raise TriageReviewValidationError("triage review API-call count is invalid")


class TriageReviewError(RuntimeError):
    """Sanitized protected-review failure."""

    def __init__(self, category: str) -> None:
        super().__init__("triage review content is unavailable")
        self.category = category
