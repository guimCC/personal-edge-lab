"""Ports for bounded Gmail discovery and durable historical triage backfills."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from personal_edge_lab.domain.email import (
    EmailDocument,
    EmailMessageId,
    EmailRetrievalRequest,
)
from personal_edge_lab.domain.email_triage_backfill import (
    TriageBackfillDiscoveryBatch,
    TriageBackfillJob,
    TriageBackfillSegment,
)


class HistoricalEmailSource(Protocol):
    def discover(self, request: EmailRetrievalRequest) -> TriageBackfillDiscoveryBatch: ...

    def retrieve_exact(self, message_id: EmailMessageId) -> EmailDocument: ...


class TriageBackfillRepository(Protocol):
    def create_job(
        self,
        *,
        job_id: str,
        starts_at: datetime,
        ends_at: datetime,
        max_messages: int,
        segments: tuple[tuple[datetime, datetime], ...],
        created_at: datetime,
    ) -> None: ...

    def get_job(self, job_id: str) -> TriageBackfillJob | None: ...

    def recent_jobs(self, *, limit: int) -> list[TriageBackfillJob]: ...

    def active_segment(self, job_id: str) -> TriageBackfillSegment | None: ...

    def record_discovery(
        self,
        *,
        job_id: str,
        segment_ordinal: int,
        message_ids: tuple[EmailMessageId, ...],
        next_cursor: str | None,
        updated_at: datetime,
    ) -> int: ...

    def claim_pending(
        self,
        *,
        job_id: str,
        limit: int,
        claimed_at: datetime,
    ) -> list[tuple[int, EmailMessageId, str]]: ...

    def complete_item(
        self,
        *,
        item_id: int,
        status: str,
        child_run_id: str,
        completed_at: datetime,
    ) -> None: ...

    def fail_item(
        self,
        *,
        item_id: int,
        category: str,
        completed_at: datetime,
        interrupted: bool = False,
    ) -> None: ...

    def pause_job(self, job_id: str, *, updated_at: datetime) -> None: ...

    def cancel_job(self, job_id: str, *, updated_at: datetime) -> None: ...

    def finalize_job(self, job_id: str, *, updated_at: datetime) -> TriageBackfillJob: ...

    def recover_interrupted(self, job_id: str, *, recovered_at: datetime) -> int: ...

    def retry_failures(self, job_id: str, *, updated_at: datetime) -> int: ...

    def close(self) -> None: ...
