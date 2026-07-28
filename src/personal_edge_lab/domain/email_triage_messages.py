"""Pure contracts for the message-centric email-triage workspace."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from personal_edge_lab.domain.email import EmailContentSource
from personal_edge_lab.domain.email_triage import PromptSourceKind, TriageLabel
from personal_edge_lab.domain.email_triage_runs import TriageRunItemStatus

MAX_TRIAGE_MESSAGES = 100
RECORD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TriageMessageValidationError(ValueError):
    """Raised when stored message data violates the bounded contract."""


class TriageMessageFilter(StrEnum):
    ALL = "all"
    RECOMMENDATIONS = "recommendations"
    ISSUES = "issues"


@dataclass(frozen=True, slots=True)
class TriageMessageCursor:
    received_at: datetime
    record_id: str

    def __post_init__(self) -> None:
        _aware(self.received_at, "message cursor timestamp")
        _record_id(self.record_id)


@dataclass(frozen=True, slots=True)
class StoredTriageMessage:
    database_id: int
    record_id: str
    content_snapshot_id: int

    def __post_init__(self) -> None:
        if isinstance(self.database_id, bool) or self.database_id < 1:
            raise TriageMessageValidationError("stored message ID is invalid")
        _record_id(self.record_id)
        if isinstance(self.content_snapshot_id, bool) or self.content_snapshot_id < 1:
            raise TriageMessageValidationError("stored content snapshot ID is invalid")


@dataclass(frozen=True, slots=True)
class TriageContentSnapshot:
    sender: str
    subject: str
    normalized_text: str
    model_input: str
    normalized_sha256: str
    model_input_sha256: str
    original_size_bytes: int
    content_source: EmailContentSource
    cleanup_flags: tuple[str, ...]
    source_truncated: bool
    model_input_truncated: bool
    metadata_truncated: bool

    def __post_init__(self) -> None:
        if not self.sender.strip() or len(self.sender) > 160:
            raise TriageMessageValidationError("stored sender is invalid")
        if len(self.subject) > 256:
            raise TriageMessageValidationError("stored subject is invalid")
        if len(self.normalized_text) > 8_000:
            raise TriageMessageValidationError("stored normalized content is too large")
        if len(self.model_input) > 1_600:
            raise TriageMessageValidationError("stored model input is too large")
        if not self.normalized_text.startswith(self.model_input):
            raise TriageMessageValidationError("stored model input is inconsistent")
        _hash(self.normalized_sha256, "stored normalized hash")
        _hash(self.model_input_sha256, "stored model-input hash")
        if isinstance(self.original_size_bytes, bool) or self.original_size_bytes < 0:
            raise TriageMessageValidationError("stored source size is invalid")
        if not isinstance(self.content_source, EmailContentSource):
            raise TriageMessageValidationError("stored content source is invalid")
        if not all(isinstance(flag, str) and flag for flag in self.cleanup_flags):
            raise TriageMessageValidationError("stored cleanup evidence is invalid")
        flags = (
            self.source_truncated,
            self.model_input_truncated,
            self.metadata_truncated,
        )
        if not all(isinstance(value, bool) for value in flags):
            raise TriageMessageValidationError("stored truncation evidence is invalid")


@dataclass(frozen=True, slots=True)
class TriageMessageSummary:
    record_id: str
    received_at: datetime
    sender: str
    subject: str
    label: TriageLabel | None
    reason: str | None
    latest_status: TriageRunItemStatus
    latest_failure_category: str | None
    last_triaged_at: datetime
    model_input_truncated: bool
    source_truncated: bool
    has_recommendation: bool

    def __post_init__(self) -> None:
        _record_id(self.record_id)
        _aware(self.received_at, "message receipt timestamp")
        _aware(self.last_triaged_at, "message triage timestamp")
        if not self.sender.strip() or len(self.sender) > 160:
            raise TriageMessageValidationError("message sender is invalid")
        if len(self.subject) > 256:
            raise TriageMessageValidationError("message subject is invalid")
        if self.label is not None and not isinstance(self.label, TriageLabel):
            raise TriageMessageValidationError("message label is invalid")
        if self.reason is not None and (not self.reason.strip() or len(self.reason) > 160):
            raise TriageMessageValidationError("message reason is invalid")
        if not isinstance(self.latest_status, TriageRunItemStatus):
            raise TriageMessageValidationError("message processing status is invalid")
        if self.has_recommendation != (self.label is not None and self.reason is not None):
            raise TriageMessageValidationError("message recommendation state is inconsistent")
        if not self.has_recommendation and (self.label is not None or self.reason is not None):
            raise TriageMessageValidationError("message recommendation is inconsistent")


@dataclass(frozen=True, slots=True)
class TriageMessageTechnicalEvidence:
    run_id: str
    item_ordinal: int
    attempt_id: int | None
    decision_sha256: str | None
    prompt_source: PromptSourceKind | None
    prompt_version: str | None
    profile_version: str | None
    taxonomy_version: str | None
    schema_version: str | None
    generation_parameters_version: str | None
    provider: str | None
    model_alias: str | None
    trace_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    queue_wait_seconds: float | None
    provider_seconds: float | None
    total_seconds: float | None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise TriageMessageValidationError("message run identity is invalid")
        if isinstance(self.item_ordinal, bool) or not 1 <= self.item_ordinal <= 10:
            raise TriageMessageValidationError("message item ordinal is invalid")
        if self.attempt_id is not None and (
            isinstance(self.attempt_id, bool) or self.attempt_id < 1
        ):
            raise TriageMessageValidationError("message attempt identity is invalid")
        if self.decision_sha256 is not None:
            _hash(self.decision_sha256, "message decision hash")
        token_values = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        if any(
            value is not None and (isinstance(value, bool) or value < 0) for value in token_values
        ):
            raise TriageMessageValidationError("message token evidence is invalid")
        timing_values = (self.queue_wait_seconds, self.provider_seconds, self.total_seconds)
        if any(
            value is not None
            and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            )
            for value in timing_values
        ):
            raise TriageMessageValidationError("message timing evidence is invalid")


@dataclass(frozen=True, slots=True)
class TriageMessageDetail:
    summary: TriageMessageSummary
    normalized_text: str
    model_input: str
    normalized_sha256: str
    model_input_sha256: str
    original_size_bytes: int
    content_source: EmailContentSource
    cleanup_flags: tuple[str, ...]
    metadata_truncated: bool
    technical: TriageMessageTechnicalEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.summary, TriageMessageSummary):
            raise TriageMessageValidationError("message summary is invalid")
        if len(self.normalized_text) > 8_000 or len(self.model_input) > 1_600:
            raise TriageMessageValidationError("message detail content is too large")
        if not self.normalized_text.startswith(self.model_input):
            raise TriageMessageValidationError("message detail model input is inconsistent")
        _hash(self.normalized_sha256, "message normalized hash")
        _hash(self.model_input_sha256, "message model-input hash")
        if isinstance(self.original_size_bytes, bool) or self.original_size_bytes < 0:
            raise TriageMessageValidationError("message source size is invalid")
        if not isinstance(self.content_source, EmailContentSource):
            raise TriageMessageValidationError("message content source is invalid")
        if not isinstance(self.technical, TriageMessageTechnicalEvidence):
            raise TriageMessageValidationError("message technical evidence is invalid")


@dataclass(frozen=True, slots=True)
class TriageMessagePage:
    items: tuple[TriageMessageSummary, ...]
    next_cursor: TriageMessageCursor | None

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or len(self.items) > MAX_TRIAGE_MESSAGES:
            raise TriageMessageValidationError("message page is invalid")


def validate_message_limit(limit: int) -> int:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_TRIAGE_MESSAGES
    ):
        raise TriageMessageValidationError(
            f"message limit must be from 1 through {MAX_TRIAGE_MESSAGES}"
        )
    return limit


def _record_id(value: str) -> None:
    if RECORD_ID_PATTERN.fullmatch(value) is None:
        raise TriageMessageValidationError("message record ID is invalid")


def _hash(value: str, name: str) -> None:
    if HASH_PATTERN.fullmatch(value) is None:
        raise TriageMessageValidationError(f"{name} is invalid")


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TriageMessageValidationError(f"{name} must include a timezone")
