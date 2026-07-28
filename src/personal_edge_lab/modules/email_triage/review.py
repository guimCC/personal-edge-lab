"""Protected, transient review of durable triage recommendations."""

from __future__ import annotations

import time
from collections.abc import Callable

from personal_edge_lab.application.ports.email_triage_review import (
    ExactEmailSource,
    TriageReviewRepository,
)
from personal_edge_lab.domain.email_triage_review import (
    TriageReviewContent,
    TriageReviewError,
    TriageRunFilter,
)
from personal_edge_lab.domain.email_triage_runs import (
    TriageRunDetails,
    TriageRunSummary,
    validate_recent_run_limit,
)
from personal_edge_lab.modules.email_triage.input import prepare_triage_input


class ReviewEmailTriageRuns:
    def __init__(
        self,
        *,
        repository: TriageReviewRepository,
        email_source: ExactEmailSource,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._repository = repository
        self._email_source = email_source
        self._monotonic = monotonic

    def recent(
        self,
        *,
        limit: int,
        run_filter: TriageRunFilter,
    ) -> list[TriageRunSummary]:
        validate_recent_run_limit(limit)
        return self._repository.review_recent(limit=limit, run_filter=run_filter)

    def get(self, run_id: str) -> TriageRunDetails | None:
        return self._repository.get(run_id)

    def content(self, run_id: str, ordinal: int) -> TriageReviewContent:
        started = self._monotonic()
        reference = self._repository.review_reference(run_id, ordinal)
        if reference is None:
            raise TriageReviewError("not_found")
        if (
            reference.message_id is None
            or reference.label is None
            or reference.normalized_sha256 is None
            or reference.model_input_sha256 is None
            or reference.model_message_chars is None
        ):
            raise TriageReviewError("content_unavailable")
        document = self._email_source.retrieve_exact(reference.message_id)
        evidence, email = prepare_triage_input(document)
        if evidence.message_fingerprint != reference.message_fingerprint:
            raise TriageReviewError("content_mismatch")
        if (
            evidence.normalized_sha256 != reference.normalized_sha256
            or evidence.model_input_sha256 != reference.model_input_sha256
            or evidence.model_message_chars != reference.model_message_chars
        ):
            raise TriageReviewError("content_mismatch")
        return TriageReviewContent(
            run_id=run_id,
            ordinal=ordinal,
            message_fingerprint=reference.message_fingerprint,
            sender=document.sender,
            subject=document.subject,
            model_input=email.message,
            normalized_remainder=document.text[len(email.message) :],
            normalized_chars=len(document.text),
            model_input_chars=len(email.message),
            content_source=document.content_source,
            cleanup_flags=evidence.cleanup_flags,
            source_truncated=document.truncated,
            model_input_truncated=evidence.model_input_truncated,
            metadata_truncated=document.metadata_truncated,
            identity_verified=True,
            elapsed_seconds=self._monotonic() - started,
            api_call_count=1,
        )
