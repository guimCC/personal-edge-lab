"""Ports for durable owner feedback and optional external publication."""

from __future__ import annotations

from typing import Protocol

from personal_edge_lab.domain.email_triage_feedback import (
    TriageFeedbackCandidate,
    TriageFeedbackCommand,
    TriageFeedbackOverview,
    TriageFeedbackPublication,
    TriageFeedbackRecord,
)


class TriageFeedbackRepository(Protocol):
    def feedback_candidate(self, record_id: str) -> TriageFeedbackCandidate | None: ...

    def next_feedback_candidate(self) -> TriageFeedbackCandidate | None: ...

    def record_feedback(self, command: TriageFeedbackCommand) -> TriageFeedbackRecord: ...

    def pending_feedback_publications(
        self,
        *,
        limit: int,
        feedback_id: str | None = None,
    ) -> tuple[TriageFeedbackPublication, ...]: ...

    def mark_feedback_synced(self, feedback_id: str) -> None: ...

    def mark_feedback_unavailable(self, feedback_id: str) -> None: ...

    def feedback_overview(self) -> TriageFeedbackOverview: ...


class TriageFeedbackPublisher(Protocol):
    def publish(self, publication: TriageFeedbackPublication) -> None: ...

    def close(self) -> None: ...


class NoOpTriageFeedbackPublisher:
    def publish(self, publication: TriageFeedbackPublication) -> None:
        del publication

    def close(self) -> None:
        pass
