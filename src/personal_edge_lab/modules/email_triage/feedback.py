"""Shared owner-feedback use case for dashboard and Telegram."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from personal_edge_lab.application.ports.email_triage_feedback import (
    TriageFeedbackPublisher,
    TriageFeedbackRepository,
)
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_feedback import (
    TriageFeedbackAction,
    TriageFeedbackCandidate,
    TriageFeedbackCommand,
    TriageFeedbackError,
    TriageFeedbackRecord,
    TriageFeedbackSource,
)


class RecordTriageFeedback:
    def __init__(
        self,
        repository: TriageFeedbackRepository,
        *,
        publisher: TriageFeedbackPublisher | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._clock = clock

    def next_candidate(self) -> TriageFeedbackCandidate | None:
        return self._repository.next_feedback_candidate()

    def candidate(self, record_id: str) -> TriageFeedbackCandidate | None:
        return self._repository.feedback_candidate(record_id)

    def record(
        self,
        *,
        record_id: str,
        recommendation_attempt_id: int,
        expected_version: int,
        action: TriageFeedbackAction,
        corrected_label: TriageLabel | None,
        source: TriageFeedbackSource,
        feedback_id: str | None = None,
    ) -> TriageFeedbackRecord:
        candidate = self._repository.feedback_candidate(record_id)
        if candidate is None:
            raise TriageFeedbackError("feedback recommendation is unavailable")
        if candidate.recommendation_label.is_legacy and (action is TriageFeedbackAction.CONFIRM):
            raise TriageFeedbackError("legacy recommendations must be corrected or dismissed")
        if corrected_label is not None and corrected_label.is_legacy:
            raise TriageFeedbackError("feedback must use the current taxonomy")
        command = TriageFeedbackCommand(
            feedback_id=feedback_id or uuid4().hex,
            record_id=record_id,
            recommendation_attempt_id=recommendation_attempt_id,
            expected_version=expected_version,
            action=action,
            corrected_label=corrected_label,
            source=source,
            created_at=self._clock(),
        )
        result = self._repository.record_feedback(command)
        self.sync_pending(feedback_id=result.feedback_id, limit=1)
        refreshed = self._repository.feedback_candidate(record_id)
        if refreshed is None or refreshed.latest_feedback is None:
            raise TriageFeedbackError("recorded feedback is unavailable")
        return refreshed.latest_feedback

    def sync_pending(self, *, feedback_id: str | None = None, limit: int = 20) -> int:
        if self._publisher is None:
            return 0
        synced = 0
        for publication in self._repository.pending_feedback_publications(
            limit=limit,
            feedback_id=feedback_id,
        ):
            try:
                self._publisher.publish(publication)
            except Exception:
                self._repository.mark_feedback_unavailable(publication.feedback.feedback_id)
            else:
                self._repository.mark_feedback_synced(publication.feedback.feedback_id)
                synced += 1
        return synced
