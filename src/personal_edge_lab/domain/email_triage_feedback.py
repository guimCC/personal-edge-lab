"""Pure contracts for owner feedback on email-triage recommendations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from personal_edge_lab.domain.email import EmailContentSource
from personal_edge_lab.domain.email_triage import TriageLabel

RECORD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
FEEDBACK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TriageFeedbackError(ValueError):
    """Raised when feedback is invalid, stale, or cannot be associated safely."""


class TriageFeedbackAction(StrEnum):
    CONFIRM = "confirm"
    CORRECT = "correct"
    DISMISS = "dismiss"


class TriageFeedbackSource(StrEnum):
    DASHBOARD = "dashboard"
    TELEGRAM = "telegram"


class TriageFeedbackSyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TriageFeedbackCommand:
    feedback_id: str
    record_id: str
    recommendation_attempt_id: int
    expected_version: int
    action: TriageFeedbackAction
    corrected_label: TriageLabel | None
    source: TriageFeedbackSource
    created_at: datetime

    def __post_init__(self) -> None:
        if FEEDBACK_ID_PATTERN.fullmatch(self.feedback_id) is None:
            raise TriageFeedbackError("feedback ID is invalid")
        _record_id(self.record_id)
        if isinstance(self.recommendation_attempt_id, bool) or self.recommendation_attempt_id < 1:
            raise TriageFeedbackError("feedback recommendation identity is invalid")
        if isinstance(self.expected_version, bool) or self.expected_version < 0:
            raise TriageFeedbackError("feedback version is invalid")
        if not isinstance(self.action, TriageFeedbackAction):
            raise TriageFeedbackError("feedback action is invalid")
        if not isinstance(self.source, TriageFeedbackSource):
            raise TriageFeedbackError("feedback source is invalid")
        if self.action is TriageFeedbackAction.CORRECT:
            if self.corrected_label is None:
                raise TriageFeedbackError("corrected feedback requires a label")
        elif self.corrected_label is not None:
            raise TriageFeedbackError("only corrected feedback may include a label")
        _aware(self.created_at, "feedback timestamp")


@dataclass(frozen=True, slots=True)
class TriageFeedbackRecord:
    feedback_id: str
    record_id: str
    version: int
    recommendation_attempt_id: int
    recommendation_label: TriageLabel
    action: TriageFeedbackAction
    expected_label: TriageLabel | None
    source: TriageFeedbackSource
    created_at: datetime
    sync_status: TriageFeedbackSyncStatus

    def __post_init__(self) -> None:
        if FEEDBACK_ID_PATTERN.fullmatch(self.feedback_id) is None:
            raise TriageFeedbackError("stored feedback ID is invalid")
        _record_id(self.record_id)
        if isinstance(self.version, bool) or self.version < 1:
            raise TriageFeedbackError("stored feedback version is invalid")
        if isinstance(self.recommendation_attempt_id, bool) or self.recommendation_attempt_id < 1:
            raise TriageFeedbackError("stored recommendation identity is invalid")
        if not isinstance(self.recommendation_label, TriageLabel):
            raise TriageFeedbackError("stored recommendation label is invalid")
        if self.action is TriageFeedbackAction.DISMISS:
            if self.expected_label is not None:
                raise TriageFeedbackError("dismissed feedback cannot have an expected label")
        elif not isinstance(self.expected_label, TriageLabel):
            raise TriageFeedbackError("stored expected label is invalid")
        if self.action is TriageFeedbackAction.CONFIRM and (
            self.expected_label is not self.recommendation_label
        ):
            raise TriageFeedbackError("confirmed feedback must retain the recommendation")
        if self.action is TriageFeedbackAction.CORRECT and (
            self.expected_label is self.recommendation_label
        ):
            raise TriageFeedbackError("corrected feedback must change the recommendation")
        if not isinstance(self.source, TriageFeedbackSource):
            raise TriageFeedbackError("stored feedback source is invalid")
        if not isinstance(self.sync_status, TriageFeedbackSyncStatus):
            raise TriageFeedbackError("stored feedback sync status is invalid")
        _aware(self.created_at, "stored feedback timestamp")


@dataclass(frozen=True, slots=True)
class TriageFeedbackCandidate:
    record_id: str
    feedback_version: int
    recommendation_attempt_id: int
    recommendation_label: TriageLabel
    reason: str | None
    sender: str
    subject: str
    received_at: datetime
    model_input: str
    normalized_sha256: str
    model_input_sha256: str
    content_source: EmailContentSource
    cleanup_flags: tuple[str, ...]
    source_truncated: bool
    model_input_truncated: bool
    trace_id: str | None
    latest_feedback: TriageFeedbackRecord | None

    def __post_init__(self) -> None:
        _record_id(self.record_id)
        if isinstance(self.feedback_version, bool) or self.feedback_version < 0:
            raise TriageFeedbackError("candidate feedback version is invalid")
        if isinstance(self.recommendation_attempt_id, bool) or self.recommendation_attempt_id < 1:
            raise TriageFeedbackError("candidate recommendation identity is invalid")
        if not isinstance(self.recommendation_label, TriageLabel):
            raise TriageFeedbackError("candidate recommendation label is invalid")
        if self.reason is not None and (not self.reason.strip() or len(self.reason) > 160):
            raise TriageFeedbackError("candidate reason is invalid")
        if not self.sender.strip() or len(self.sender) > 160:
            raise TriageFeedbackError("candidate sender is invalid")
        if len(self.subject) > 256 or len(self.model_input) > 1_600:
            raise TriageFeedbackError("candidate content is invalid")
        _aware(self.received_at, "candidate receipt timestamp")
        _hash(self.normalized_sha256)
        _hash(self.model_input_sha256)
        if not isinstance(self.content_source, EmailContentSource):
            raise TriageFeedbackError("candidate content source is invalid")
        if not all(isinstance(flag, str) and flag for flag in self.cleanup_flags):
            raise TriageFeedbackError("candidate cleanup evidence is invalid")


@dataclass(frozen=True, slots=True)
class TriageFeedbackPublication:
    feedback: TriageFeedbackRecord
    dataset_item_id: str
    trace_id: str | None
    normalized_sha256: str
    model_input_sha256: str
    sender_chars: int
    subject_chars: int
    message_chars: int
    content_source: EmailContentSource
    cleanup_flags: tuple[str, ...]
    source_truncated: bool
    model_input_truncated: bool

    def __post_init__(self) -> None:
        if not self.dataset_item_id:
            raise TriageFeedbackError("dataset item identity is invalid")
        _hash(self.normalized_sha256)
        _hash(self.model_input_sha256)
        for value in (self.sender_chars, self.subject_chars, self.message_chars):
            if isinstance(value, bool) or value < 0:
                raise TriageFeedbackError("publication length evidence is invalid")
        if not isinstance(self.content_source, EmailContentSource):
            raise TriageFeedbackError("publication content source is invalid")


@dataclass(frozen=True, slots=True)
class TriageFeedbackOverview:
    pending_count: int
    reviewed_count: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or not math.isfinite(float(value))
            for value in (self.pending_count, self.reviewed_count)
        ):
            raise TriageFeedbackError("feedback overview is invalid")


def _record_id(value: str) -> None:
    if RECORD_ID_PATTERN.fullmatch(value) is None:
        raise TriageFeedbackError("message record ID is invalid")


def _hash(value: str) -> None:
    if HASH_PATTERN.fullmatch(value) is None:
        raise TriageFeedbackError("feedback content hash is invalid")


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TriageFeedbackError(f"{name} must include a timezone")
