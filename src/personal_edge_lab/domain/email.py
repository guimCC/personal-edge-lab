"""Pure contracts for bounded, read-only email retrieval."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

MAX_EMAIL_ID_CHARS = 128
MAX_EMAIL_CURSOR_CHARS = 1024
MAX_EMAIL_QUERY_CHARS = 512
MAX_EMAIL_BATCH_SIZE = 25
MAX_EMAIL_SENDER_CHARS = 160
MAX_EMAIL_SUBJECT_CHARS = 256
MAX_EMAIL_TEXT_CHARS = 8000
MAX_EMAIL_PAGES = 3


class EmailValidationError(ValueError):
    """Raised when email-source domain data violates its bounded contract."""


class EmailContentSource(StrEnum):
    PLAIN_TEXT = "plain_text"
    HTML = "html"
    EMPTY = "empty"


class EmailItemFailureCategory(StrEnum):
    INVALID_MESSAGE = "invalid_message"
    UNSUPPORTED_MESSAGE = "unsupported_message"
    MESSAGE_TOO_LARGE = "message_too_large"


@dataclass(frozen=True, slots=True)
class EmailMessageId:
    value: str

    def __post_init__(self) -> None:
        _validate_opaque_value(self.value, "message ID", MAX_EMAIL_ID_CHARS)


@dataclass(frozen=True, slots=True)
class EmailThreadId:
    value: str

    def __post_init__(self) -> None:
        _validate_opaque_value(self.value, "thread ID", MAX_EMAIL_ID_CHARS)


@dataclass(frozen=True, slots=True)
class EmailRetrievalCursor:
    value: str

    def __post_init__(self) -> None:
        _validate_opaque_value(self.value, "retrieval cursor", MAX_EMAIL_CURSOR_CHARS)


@dataclass(frozen=True, slots=True)
class EmailRetrievalRequest:
    query: str
    limit: int = 10
    cursor: EmailRetrievalCursor | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise EmailValidationError("email query must not be blank")
        if len(self.query) > MAX_EMAIL_QUERY_CHARS:
            raise EmailValidationError(
                f"email query must not exceed {MAX_EMAIL_QUERY_CHARS} characters"
            )
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in self.query):
            raise EmailValidationError("email query must not contain control characters")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= MAX_EMAIL_BATCH_SIZE
        ):
            raise EmailValidationError(
                f"email batch limit must be from 1 through {MAX_EMAIL_BATCH_SIZE}"
            )
        if self.cursor is not None and not isinstance(self.cursor, EmailRetrievalCursor):
            raise EmailValidationError("email retrieval cursor is invalid")


@dataclass(frozen=True, slots=True)
class EmailDocument:
    message_id: EmailMessageId
    thread_id: EmailThreadId
    received_at: datetime
    sender: str
    subject: str
    text: str
    content_source: EmailContentSource
    original_size_bytes: int
    normalized_char_count: int
    truncated: bool = False
    metadata_truncated: bool = False
    quoted_text_removed: bool = False
    signature_removed: bool = False
    tracking_removed: bool = False
    duplicate_lines_removed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.message_id, EmailMessageId):
            raise EmailValidationError("email message ID is invalid")
        if not isinstance(self.thread_id, EmailThreadId):
            raise EmailValidationError("email thread ID is invalid")
        if (
            not isinstance(self.received_at, datetime)
            or self.received_at.tzinfo is None
            or self.received_at.utcoffset() is None
        ):
            raise EmailValidationError("email received timestamp must be timezone-aware")
        if not isinstance(self.sender, str) or not self.sender.strip():
            raise EmailValidationError("email sender must not be blank")
        if len(self.sender) > MAX_EMAIL_SENDER_CHARS:
            raise EmailValidationError(
                f"email sender must not exceed {MAX_EMAIL_SENDER_CHARS} characters"
            )
        if not isinstance(self.subject, str) or len(self.subject) > MAX_EMAIL_SUBJECT_CHARS:
            raise EmailValidationError(
                f"email subject must not exceed {MAX_EMAIL_SUBJECT_CHARS} characters"
            )
        if not isinstance(self.text, str) or len(self.text) > MAX_EMAIL_TEXT_CHARS:
            raise EmailValidationError(
                f"normalized email text must not exceed {MAX_EMAIL_TEXT_CHARS} characters"
            )
        if not self.subject.strip() and not self.text.strip():
            raise EmailValidationError("email subject or normalized text must not be blank")
        if not isinstance(self.content_source, EmailContentSource):
            raise EmailValidationError("email content source is invalid")
        if (
            isinstance(self.original_size_bytes, bool)
            or not isinstance(self.original_size_bytes, int)
            or self.original_size_bytes < 0
        ):
            raise EmailValidationError("email original size must be a non-negative integer")
        if self.normalized_char_count != len(self.text):
            raise EmailValidationError("normalized email character count is inconsistent")
        flags = (
            self.truncated,
            self.metadata_truncated,
            self.quoted_text_removed,
            self.signature_removed,
            self.tracking_removed,
            self.duplicate_lines_removed,
        )
        if not all(isinstance(flag, bool) for flag in flags):
            raise EmailValidationError("email cleanup flags must be boolean")


@dataclass(frozen=True, slots=True)
class EmailItemFailure:
    category: EmailItemFailureCategory

    def __post_init__(self) -> None:
        if not isinstance(self.category, EmailItemFailureCategory):
            raise EmailValidationError("email item failure category is invalid")


@dataclass(frozen=True, slots=True)
class EmailRetrievalBatch:
    documents: tuple[EmailDocument, ...]
    failures: tuple[EmailItemFailure, ...]
    next_cursor: EmailRetrievalCursor | None
    pages_fetched: int
    api_call_count: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.documents, tuple) or not all(
            isinstance(document, EmailDocument) for document in self.documents
        ):
            raise EmailValidationError("email retrieval documents are invalid")
        if len(self.documents) > MAX_EMAIL_BATCH_SIZE:
            raise EmailValidationError("email retrieval batch is too large")
        if not isinstance(self.failures, tuple) or not all(
            isinstance(failure, EmailItemFailure) for failure in self.failures
        ):
            raise EmailValidationError("email retrieval failures are invalid")
        if len(self.documents) + len(self.failures) > MAX_EMAIL_BATCH_SIZE:
            raise EmailValidationError("email retrieval result is too large")
        if self.next_cursor is not None and not isinstance(self.next_cursor, EmailRetrievalCursor):
            raise EmailValidationError("email retrieval next cursor is invalid")
        if (
            isinstance(self.pages_fetched, bool)
            or not isinstance(self.pages_fetched, int)
            or not 0 <= self.pages_fetched <= MAX_EMAIL_PAGES
        ):
            raise EmailValidationError("email retrieval page count is invalid")
        if (
            isinstance(self.api_call_count, bool)
            or not isinstance(self.api_call_count, int)
            or self.api_call_count < self.pages_fetched
        ):
            raise EmailValidationError("email retrieval API call count is invalid")
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or not math.isfinite(float(self.elapsed_seconds))
            or self.elapsed_seconds < 0
        ):
            raise EmailValidationError("email retrieval elapsed time is invalid")

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def _validate_opaque_value(value: object, label: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(character.isspace() or ord(character) < 0x20 for character in value)
    ):
        raise EmailValidationError(f"email {label} is invalid")
