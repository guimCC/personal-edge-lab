"""Pure contracts for durable, read-only mailbox triage runs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from personal_edge_lab.domain.email import EmailContentSource, EmailMessageId, EmailThreadId
from personal_edge_lab.domain.email_triage import (
    PromptSourceKind,
    TriageDecisionSource,
    TriageLabel,
    TriagePromptIdentity,
)

MAX_TRIAGE_BATCH_SIZE = 10
MAX_RECENT_RUNS = 100
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TriageRunValidationError(ValueError):
    """Raised when durable triage evidence violates its bounded contract."""


class TriageRunStatus(StrEnum):
    REQUESTED = "requested"
    RETRIEVING = "retrieving"
    CLASSIFYING = "classifying"
    COMPLETED_WITH_RESULTS = "completed_with_results"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED_BEFORE_ITEMS = "failed_before_items"
    INTERRUPTED = "interrupted"


class TriageRunItemStatus(StrEnum):
    PENDING = "pending"
    CLASSIFYING = "classifying"
    SUCCEEDED = "succeeded"
    REUSED = "reused"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TriageAttemptStatus(StrEnum):
    RESERVED = "reserved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TriageReservationStatus(StrEnum):
    NEW = "new"
    REUSED = "reused"
    CONCURRENT = "concurrent"


@dataclass(frozen=True, slots=True)
class TriageInputEvidence:
    message_id: EmailMessageId
    thread_id: EmailThreadId
    received_at: datetime
    message_fingerprint: str
    normalized_sha256: str
    model_input_sha256: str
    sender_chars: int
    subject_chars: int
    normalized_chars: int
    model_message_chars: int
    original_size_bytes: int
    content_source: EmailContentSource
    source_truncated: bool
    model_input_truncated: bool
    metadata_truncated: bool
    cleanup_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.message_id, EmailMessageId):
            raise TriageRunValidationError("triage message ID is invalid")
        if not isinstance(self.thread_id, EmailThreadId):
            raise TriageRunValidationError("triage thread ID is invalid")
        _aware(self.received_at, "triage receipt timestamp")
        _hash(self.message_fingerprint, "triage message fingerprint")
        _hash(self.normalized_sha256, "triage normalized hash")
        _hash(self.model_input_sha256, "triage model-input hash")
        counts = (
            self.sender_chars,
            self.subject_chars,
            self.normalized_chars,
            self.model_message_chars,
            self.original_size_bytes,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
        ):
            raise TriageRunValidationError("triage size evidence is invalid")
        if self.model_message_chars > self.normalized_chars:
            raise TriageRunValidationError("triage model-input length is inconsistent")
        if not isinstance(self.content_source, EmailContentSource):
            raise TriageRunValidationError("triage content source is invalid")
        flags = (
            self.source_truncated,
            self.model_input_truncated,
            self.metadata_truncated,
        )
        if not all(isinstance(value, bool) for value in flags):
            raise TriageRunValidationError("triage truncation evidence is invalid")
        if not isinstance(self.cleanup_flags, tuple) or not all(
            isinstance(value, str) and value for value in self.cleanup_flags
        ):
            raise TriageRunValidationError("triage cleanup evidence is invalid")


@dataclass(frozen=True, slots=True)
class TriageEvaluationIdentity:
    identity_sha256: str
    input: TriageInputEvidence
    profile_name: str
    profile_version: str
    taxonomy_version: str
    schema_version: str
    generation_parameters_version: str
    prompt: TriagePromptIdentity
    model_alias: str
    decision_source: TriageDecisionSource = TriageDecisionSource.MODEL
    rule_id: str | None = None
    rule_version: str | None = None

    def __post_init__(self) -> None:
        _hash(self.identity_sha256, "triage evaluation identity")
        if not isinstance(self.input, TriageInputEvidence):
            raise TriageRunValidationError("triage input evidence is invalid")
        values = (
            self.profile_name,
            self.profile_version,
            self.taxonomy_version,
            self.schema_version,
            self.generation_parameters_version,
            self.model_alias,
        )
        if any(not isinstance(value, str) or not value for value in values):
            raise TriageRunValidationError("triage evaluation version evidence is invalid")
        if not isinstance(self.prompt, TriagePromptIdentity):
            raise TriageRunValidationError("triage prompt identity is invalid")
        if not isinstance(self.decision_source, TriageDecisionSource):
            raise TriageRunValidationError("triage decision source is invalid")
        if self.decision_source is TriageDecisionSource.MODEL:
            if self.rule_id is not None or self.rule_version is not None:
                raise TriageRunValidationError("model evaluation contains rule evidence")
        elif not self.rule_id or not self.rule_version:
            raise TriageRunValidationError("rule evaluation evidence is incomplete")


@dataclass(frozen=True, slots=True)
class StoredTriageDecision:
    label: TriageLabel
    decision_sha256: str
    reason_chars: int | None
    source: TriageDecisionSource = TriageDecisionSource.MODEL
    rule_id: str | None = None
    rule_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, TriageLabel):
            raise TriageRunValidationError("stored triage label is invalid")
        _hash(self.decision_sha256, "stored triage decision hash")
        if not isinstance(self.source, TriageDecisionSource):
            raise TriageRunValidationError("stored triage source is invalid")
        if self.source is TriageDecisionSource.MODEL:
            if (
                isinstance(self.reason_chars, bool)
                or not isinstance(self.reason_chars, int)
                or not 1 <= self.reason_chars <= 160
            ):
                raise TriageRunValidationError("stored triage reason length is invalid")
            if self.rule_id is not None or self.rule_version is not None:
                raise TriageRunValidationError("stored model decision contains rule evidence")
        elif self.reason_chars is not None or not self.rule_id or not self.rule_version:
            raise TriageRunValidationError("stored rule decision evidence is invalid")


@dataclass(frozen=True, slots=True)
class TriageReservation:
    status: TriageReservationStatus
    evaluation_id: int
    attempt_id: int | None
    decision: StoredTriageDecision | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class MailboxTriageItemResult:
    ordinal: int
    message_fingerprint: str
    received_at: datetime | None
    status: TriageRunItemStatus
    sender: str | None = None
    subject: str | None = None
    label: TriageLabel | None = None
    reason: str | None = None
    failure_category: str | None = None
    trace_id: str | None = None
    prompt: TriagePromptIdentity | None = None
    provider: str | None = None
    model_alias: str | None = None
    queue_wait_seconds: float | None = None
    provider_seconds: float | None = None
    total_seconds: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    decision_source: TriageDecisionSource | None = None
    rule_id: str | None = None
    rule_version: str | None = None


@dataclass(frozen=True, slots=True)
class MailboxTriageResult:
    run_id: str
    status: TriageRunStatus
    query_sha256: str
    requested_limit: int
    items: tuple[MailboxTriageItemResult, ...]
    retrieval_failure_count: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise TriageRunValidationError("triage run ID is invalid")
        _hash(self.query_sha256, "triage query hash")
        if (
            isinstance(self.requested_limit, bool)
            or not isinstance(self.requested_limit, int)
            or not 1 <= self.requested_limit <= MAX_TRIAGE_BATCH_SIZE
        ):
            raise TriageRunValidationError("triage requested limit is invalid")
        if not isinstance(self.items, tuple):
            raise TriageRunValidationError("triage result items are invalid")
        _seconds(self.elapsed_seconds, "triage run elapsed time")

    @property
    def failure_count(self) -> int:
        return sum(
            item.status in {TriageRunItemStatus.FAILED, TriageRunItemStatus.INTERRUPTED}
            for item in self.items
        )


@dataclass(frozen=True, slots=True)
class TriageRunSummary:
    run_id: str
    status: TriageRunStatus
    query_sha256: str
    requested_limit: int
    force_new_attempt: bool
    requested_at: datetime
    completed_at: datetime | None
    document_count: int
    retrieval_failure_count: int
    succeeded_count: int
    reused_count: int
    failed_count: int
    interrupted_count: int
    query_text: str | None = None


@dataclass(frozen=True, slots=True)
class TriageRunItemSummary:
    ordinal: int
    message_fingerprint: str
    received_at: datetime | None
    status: TriageRunItemStatus
    label: TriageLabel | None
    decision_sha256: str | None
    reason_chars: int | None
    failure_category: str | None
    prompt_source: PromptSourceKind | None
    prompt_version: str | None
    profile_version: str | None
    model_alias: str | None
    trace_id: str | None
    queue_wait_seconds: float | None
    provider_seconds: float | None
    total_seconds: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    attempt_id: int | None
    review_available: bool
    decision_source: TriageDecisionSource | None = None
    rule_id: str | None = None
    rule_version: str | None = None


@dataclass(frozen=True, slots=True)
class TriageRunDetails:
    run: TriageRunSummary
    items: tuple[TriageRunItemSummary, ...]


def validate_recent_run_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RECENT_RUNS:
        raise TriageRunValidationError(f"recent-run limit must be from 1 through {MAX_RECENT_RUNS}")
    return limit


def _hash(value: object, label: str) -> None:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise TriageRunValidationError(f"{label} is invalid")


def _aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TriageRunValidationError(f"{label} must be timezone-aware")


def _seconds(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise TriageRunValidationError(f"{label} is invalid")
