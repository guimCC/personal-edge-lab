"""Pure contracts for resumable historical email-triage backfills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from personal_edge_lab.domain.email import EmailMessageId, EmailRetrievalCursor

BACKFILL_MONTHS = 12
MAX_BACKFILL_MESSAGES = 10_000
MAX_BACKFILL_STEP_ITEMS = 10


class TriageBackfillValidationError(ValueError):
    """Raised when historical-backfill evidence violates its bounded contract."""


class TriageBackfillStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    LIMIT_REACHED = "limit_reached"
    CANCELLED = "cancelled"


class TriageBackfillSegmentStatus(StrEnum):
    PENDING = "pending"
    DISCOVERING = "discovering"
    EXHAUSTED = "exhausted"


class TriageBackfillItemStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    REUSED = "reused"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class TriageBackfillSegment:
    ordinal: int
    starts_at: datetime
    ends_at: datetime
    status: TriageBackfillSegmentStatus
    cursor: EmailRetrievalCursor | None = None
    discovered_count: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.ordinal <= BACKFILL_MONTHS:
            raise TriageBackfillValidationError("backfill segment ordinal is invalid")
        _validate_timestamp(self.starts_at, "segment start")
        _validate_timestamp(self.ends_at, "segment end")
        if self.starts_at >= self.ends_at:
            raise TriageBackfillValidationError("backfill segment range is invalid")
        if not isinstance(self.status, TriageBackfillSegmentStatus):
            raise TriageBackfillValidationError("backfill segment status is invalid")
        if self.cursor is not None and not isinstance(self.cursor, EmailRetrievalCursor):
            raise TriageBackfillValidationError("backfill segment cursor is invalid")
        _validate_count(self.discovered_count, "segment discovered count")


@dataclass(frozen=True, slots=True)
class TriageBackfillDiscoveryBatch:
    message_ids: tuple[EmailMessageId, ...]
    next_cursor: EmailRetrievalCursor | None
    api_call_count: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.message_ids, tuple) or not all(
            isinstance(message_id, EmailMessageId) for message_id in self.message_ids
        ):
            raise TriageBackfillValidationError("backfill discovery IDs are invalid")
        if len(self.message_ids) > 25:
            raise TriageBackfillValidationError("backfill discovery batch is too large")
        if len(set(self.message_ids)) != len(self.message_ids):
            raise TriageBackfillValidationError("backfill discovery IDs must be unique")
        if self.next_cursor is not None and not isinstance(self.next_cursor, EmailRetrievalCursor):
            raise TriageBackfillValidationError("backfill discovery cursor is invalid")
        _validate_count(self.api_call_count, "backfill API call count")
        if self.api_call_count < 1:
            raise TriageBackfillValidationError("backfill discovery must make one API call")
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or not math.isfinite(float(self.elapsed_seconds))
            or self.elapsed_seconds < 0
        ):
            raise TriageBackfillValidationError("backfill elapsed time is invalid")


@dataclass(frozen=True, slots=True)
class TriageBackfillJob:
    job_id: str
    status: TriageBackfillStatus
    starts_at: datetime
    ends_at: datetime
    max_messages: int
    created_at: datetime
    updated_at: datetime
    discovered_count: int
    pending_count: int
    succeeded_count: int
    reused_count: int
    failed_count: int
    interrupted_count: int
    segments_exhausted: int
    active_segment: int | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.job_id, str)
            or len(self.job_id) != 32
            or any(character not in "0123456789abcdef" for character in self.job_id)
        ):
            raise TriageBackfillValidationError("backfill job ID is invalid")
        if not isinstance(self.status, TriageBackfillStatus):
            raise TriageBackfillValidationError("backfill job status is invalid")
        for value, label in (
            (self.starts_at, "start"),
            (self.ends_at, "end"),
            (self.created_at, "creation"),
            (self.updated_at, "update"),
        ):
            _validate_timestamp(value, label)
        if self.starts_at >= self.ends_at:
            raise TriageBackfillValidationError("backfill date range is invalid")
        if (
            isinstance(self.max_messages, bool)
            or not isinstance(self.max_messages, int)
            or not 1 <= self.max_messages <= MAX_BACKFILL_MESSAGES
        ):
            raise TriageBackfillValidationError("backfill maximum is invalid")
        for value, label in (
            (self.discovered_count, "discovered"),
            (self.pending_count, "pending"),
            (self.succeeded_count, "succeeded"),
            (self.reused_count, "reused"),
            (self.failed_count, "failed"),
            (self.interrupted_count, "interrupted"),
            (self.segments_exhausted, "segments exhausted"),
        ):
            _validate_count(value, label)
        if self.segments_exhausted > BACKFILL_MONTHS:
            raise TriageBackfillValidationError("backfill exhausted segment count is invalid")
        if self.active_segment is not None and not 1 <= self.active_segment <= BACKFILL_MONTHS:
            raise TriageBackfillValidationError("backfill active segment is invalid")

    @property
    def terminal_count(self) -> int:
        return self.succeeded_count + self.reused_count + self.failed_count + self.interrupted_count


@dataclass(frozen=True, slots=True)
class TriageBackfillStepResult:
    job: TriageBackfillJob
    discovered_now: int
    processed_now: int
    api_call_count: int
    child_run_ids: tuple[str, ...]
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.job, TriageBackfillJob):
            raise TriageBackfillValidationError("backfill step job is invalid")
        for value, label in (
            (self.discovered_now, "step discovered"),
            (self.processed_now, "step processed"),
            (self.api_call_count, "step API call"),
        ):
            _validate_count(value, label)
        if self.processed_now > MAX_BACKFILL_STEP_ITEMS:
            raise TriageBackfillValidationError("backfill step processed too many items")
        if not isinstance(self.child_run_ids, tuple) or not all(
            isinstance(value, str) and value for value in self.child_run_ids
        ):
            raise TriageBackfillValidationError("backfill child run IDs are invalid")
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or not math.isfinite(float(self.elapsed_seconds))
            or self.elapsed_seconds < 0
        ):
            raise TriageBackfillValidationError("backfill step elapsed time is invalid")


def validate_backfill_step_items(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_BACKFILL_STEP_ITEMS
    ):
        raise TriageBackfillValidationError(
            f"backfill step items must be from 1 through {MAX_BACKFILL_STEP_ITEMS}"
        )
    return value


def _validate_timestamp(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TriageBackfillValidationError(f"backfill {label} timestamp must be timezone-aware")


def _validate_count(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TriageBackfillValidationError(f"backfill {label} count is invalid")
