"""Ports for protected, read-only triage review."""

from __future__ import annotations

from typing import Protocol

from personal_edge_lab.domain.email import EmailDocument, EmailMessageId
from personal_edge_lab.domain.email_triage_review import (
    TriageReviewReference,
    TriageRunFilter,
)
from personal_edge_lab.domain.email_triage_runs import TriageRunDetails, TriageRunSummary


class ExactEmailSource(Protocol):
    def retrieve_exact(self, message_id: EmailMessageId) -> EmailDocument: ...


class TriageReviewRepository(Protocol):
    def review_recent(
        self,
        *,
        limit: int,
        run_filter: TriageRunFilter,
    ) -> list[TriageRunSummary]: ...

    def get(self, run_id: str) -> TriageRunDetails | None: ...

    def review_reference(
        self,
        run_id: str,
        ordinal: int,
    ) -> TriageReviewReference | None: ...

    def close(self) -> None: ...
