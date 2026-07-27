from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_edge_lab.domain.email import (
    MAX_EMAIL_BATCH_SIZE,
    MAX_EMAIL_QUERY_CHARS,
    EmailContentSource,
    EmailDocument,
    EmailItemFailure,
    EmailItemFailureCategory,
    EmailMessageId,
    EmailRetrievalBatch,
    EmailRetrievalCursor,
    EmailRetrievalRequest,
    EmailThreadId,
    EmailValidationError,
)


def _document(**changes: object) -> EmailDocument:
    values: dict[str, object] = {
        "message_id": EmailMessageId("message-1"),
        "thread_id": EmailThreadId("thread-1"),
        "received_at": datetime(2026, 7, 27, 8, 30, tzinfo=UTC),
        "sender": "Billing <billing@example.test>",
        "subject": "Invoice",
        "text": "Your invoice is attached.",
        "content_source": EmailContentSource.PLAIN_TEXT,
        "original_size_bytes": 1200,
        "normalized_char_count": 25,
    }
    values.update(changes)
    return EmailDocument(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "with space", "\n", "x" * 129])
def test_opaque_email_ids_are_bounded(value: str) -> None:
    with pytest.raises(EmailValidationError):
        EmailMessageId(value)


def test_retrieval_request_accepts_explicit_bounded_query_and_cursor() -> None:
    request = EmailRetrievalRequest(
        query="in:inbox newer_than:7d",
        limit=10,
        cursor=EmailRetrievalCursor("next-token"),
    )

    assert request.limit == 10
    assert request.cursor == EmailRetrievalCursor("next-token")


@pytest.mark.parametrize(
    ("query", "limit"),
    [
        ("", 10),
        (" ", 10),
        ("in:inbox\nfrom:someone", 10),
        ("x" * (MAX_EMAIL_QUERY_CHARS + 1), 10),
        ("in:inbox", 0),
        ("in:inbox", MAX_EMAIL_BATCH_SIZE + 1),
        ("in:inbox", True),
    ],
)
def test_retrieval_request_rejects_invalid_bounds(query: str, limit: object) -> None:
    with pytest.raises(EmailValidationError):
        EmailRetrievalRequest(query=query, limit=limit)  # type: ignore[arg-type]


def test_document_preserves_normalization_evidence() -> None:
    document = _document(
        truncated=True,
        metadata_truncated=True,
        quoted_text_removed=True,
        signature_removed=True,
        tracking_removed=True,
        duplicate_lines_removed=True,
    )

    assert document.normalized_char_count == len(document.text)
    assert document.truncated
    assert document.metadata_truncated
    assert document.quoted_text_removed
    assert document.signature_removed
    assert document.tracking_removed
    assert document.duplicate_lines_removed


@pytest.mark.parametrize(
    "changes",
    [
        {"received_at": datetime(2026, 7, 27)},
        {"sender": ""},
        {"subject": "", "text": "", "normalized_char_count": 0},
        {"normalized_char_count": 1},
        {"original_size_bytes": -1},
        {"truncated": 1},
    ],
)
def test_document_rejects_inconsistent_or_unbounded_values(changes: dict[str, object]) -> None:
    with pytest.raises(EmailValidationError):
        _document(**changes)


def test_batch_exposes_successes_failures_and_opaque_continuation() -> None:
    batch = EmailRetrievalBatch(
        documents=(_document(),),
        failures=(EmailItemFailure(EmailItemFailureCategory.UNSUPPORTED_MESSAGE),),
        next_cursor=EmailRetrievalCursor("next"),
        pages_fetched=1,
        api_call_count=2,
        elapsed_seconds=0.25,
    )

    assert batch.has_more
    assert len(batch.documents) == 1
    assert len(batch.failures) == 1


def test_empty_batch_is_valid() -> None:
    batch = EmailRetrievalBatch(
        documents=(),
        failures=(),
        next_cursor=None,
        pages_fetched=1,
        api_call_count=1,
        elapsed_seconds=0,
    )

    assert not batch.has_more
