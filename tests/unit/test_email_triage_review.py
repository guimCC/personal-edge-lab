from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from personal_edge_lab.domain.email import (
    EmailContentSource,
    EmailDocument,
    EmailMessageId,
    EmailThreadId,
)
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_review import (
    TriageReviewError,
    TriageReviewReference,
    TriageRunFilter,
)
from personal_edge_lab.domain.email_triage_runs import TriageRunItemStatus
from personal_edge_lab.modules.email_triage.input import prepare_triage_input
from personal_edge_lab.modules.email_triage.review import ReviewEmailTriageRuns

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _document(*, text: str = "x" * 1800) -> EmailDocument:
    return EmailDocument(
        message_id=EmailMessageId("message-1"),
        thread_id=EmailThreadId("thread-1"),
        received_at=NOW,
        sender="Sender <sender@example.test>",
        subject="Private subject",
        text=text,
        content_source=EmailContentSource.PLAIN_TEXT,
        original_size_bytes=2000,
        normalized_char_count=len(text),
        truncated=False,
        metadata_truncated=False,
        quoted_text_removed=True,
        signature_removed=False,
        tracking_removed=False,
        duplicate_lines_removed=False,
    )


class _Repository:
    def __init__(self, reference: TriageReviewReference | None) -> None:
        self.reference = reference

    def review_recent(self, *, limit, run_filter):
        assert limit == 20
        assert run_filter is TriageRunFilter.ALL
        return []

    def get(self, run_id):
        return None

    def review_reference(self, run_id, ordinal):
        assert run_id == "run-1"
        assert ordinal == 1
        return self.reference

    def close(self):
        return None


class _Source:
    def __init__(self, document: EmailDocument) -> None:
        self.document = document
        self.calls = 0

    def retrieve_exact(self, message_id: EmailMessageId) -> EmailDocument:
        self.calls += 1
        assert message_id == self.document.message_id
        return self.document


def _reference(document: EmailDocument) -> TriageReviewReference:
    evidence, _email = prepare_triage_input(document)
    return TriageReviewReference(
        run_id="run-1",
        ordinal=1,
        message_id=document.message_id,
        message_fingerprint=evidence.message_fingerprint,
        item_status=TriageRunItemStatus.SUCCEEDED,
        label=TriageLabel.JOB,
        normalized_sha256=evidence.normalized_sha256,
        model_input_sha256=evidence.model_input_sha256,
        model_message_chars=evidence.model_message_chars,
    )


def test_review_returns_exact_model_content_and_normalized_remainder() -> None:
    document = _document()
    source = _Source(document)
    service = ReviewEmailTriageRuns(
        repository=_Repository(_reference(document)),
        email_source=source,
        monotonic=iter((10.0, 10.25)).__next__,
    )

    content = service.content("run-1", 1)

    assert content.model_input == "x" * 1600
    assert content.normalized_remainder == "x" * 200
    assert content.identity_verified is True
    assert content.api_call_count == 1
    assert source.calls == 1


def test_review_refuses_changed_content() -> None:
    original = _document(text="original")
    changed = replace(original, text="changed", normalized_char_count=7)

    with pytest.raises(TriageReviewError) as caught:
        ReviewEmailTriageRuns(
            repository=_Repository(_reference(original)),
            email_source=_Source(changed),
        ).content("run-1", 1)

    assert caught.value.category == "content_mismatch"


def test_review_without_stored_input_identity_never_contacts_gmail() -> None:
    document = _document()
    reference = replace(
        _reference(document),
        normalized_sha256=None,
        model_input_sha256=None,
        model_message_chars=None,
    )
    source = _Source(document)

    with pytest.raises(TriageReviewError) as caught:
        ReviewEmailTriageRuns(
            repository=_Repository(reference),
            email_source=source,
        ).content("run-1", 1)

    assert caught.value.category == "content_unavailable"
    assert source.calls == 0
