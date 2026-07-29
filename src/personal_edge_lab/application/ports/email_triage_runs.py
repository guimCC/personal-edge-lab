"""Application port for durable mailbox-triage evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from personal_edge_lab.domain.ai import CompletionResult
from personal_edge_lab.domain.email import EmailDocument, EmailItemFailure
from personal_edge_lab.domain.email_triage import TriageDecision
from personal_edge_lab.domain.email_triage_messages import StoredTriageMessage
from personal_edge_lab.domain.email_triage_runs import (
    TriageEvaluationIdentity,
    TriageInputEvidence,
    TriageReservation,
    TriageRunDetails,
    TriageRunStatus,
    TriageRunSummary,
)


class TriageRunRepository(Protocol):
    def recover_stale(self, *, stale_before: datetime, recovered_at: datetime) -> int: ...

    def create_run(
        self,
        *,
        run_id: str,
        operation_id: str,
        query_sha256: str,
        requested_limit: int,
        force_new_attempt: bool,
        requested_at: datetime,
        query_text: str = "",
    ) -> None: ...

    def mark_retrieving(self, run_id: str, *, updated_at: datetime) -> None: ...

    def record_retrieval(
        self,
        run_id: str,
        *,
        document_count: int,
        failure_count: int,
        pages_fetched: int,
        api_call_count: int,
        elapsed_seconds: float,
        has_more: bool,
        updated_at: datetime,
    ) -> None: ...

    def fail_before_items(
        self,
        run_id: str,
        *,
        category: str,
        completed_at: datetime,
    ) -> None: ...

    def record_source_failure(
        self,
        run_id: str,
        *,
        ordinal: int,
        failure: EmailItemFailure,
        recorded_at: datetime,
    ) -> None: ...

    def store_message(
        self,
        *,
        run_id: str,
        ordinal: int,
        document: EmailDocument,
        evidence: TriageInputEvidence,
        model_input: str,
        recorded_at: datetime,
    ) -> StoredTriageMessage: ...

    def reserve(
        self,
        run_id: str,
        *,
        ordinal: int,
        identity: TriageEvaluationIdentity,
        operation_id: str,
        force_new_attempt: bool,
        reserved_at: datetime,
        message_record_id: int | None = None,
        content_snapshot_id: int | None = None,
    ) -> TriageReservation: ...

    def mark_attempt_running(
        self,
        *,
        attempt_id: int,
        run_id: str,
        ordinal: int,
        started_at: datetime,
    ) -> None: ...

    def complete_attempt(
        self,
        *,
        attempt_id: int,
        run_id: str,
        ordinal: int,
        decision: TriageDecision,
        completion: CompletionResult,
        trace_id: str | None,
        trace_unavailable: bool,
        completed_at: datetime,
    ) -> None: ...

    def complete_rule_attempt(
        self,
        *,
        attempt_id: int,
        run_id: str,
        ordinal: int,
        decision: TriageDecision,
        completed_at: datetime,
    ) -> None: ...

    def fail_attempt(
        self,
        *,
        attempt_id: int | None,
        run_id: str,
        ordinal: int,
        category: str,
        provider: str | None,
        model_alias: str | None,
        queue_wait_seconds: float,
        provider_seconds: float | None,
        attempt_count: int,
        retry_eligible: bool | None,
        retry_after_seconds: float | None,
        trace_id: str | None,
        trace_unavailable: bool,
        completed_at: datetime,
    ) -> None: ...

    def record_item_failure(
        self,
        run_id: str,
        *,
        ordinal: int,
        message_id: str | None,
        message_fingerprint: str,
        received_at: datetime | None,
        message_record_id: int | None,
        category: str,
        recorded_at: datetime,
        interrupted: bool = False,
    ) -> None: ...

    def interrupt_pending(
        self,
        run_id: str,
        *,
        starting_ordinal: int,
        completed_at: datetime,
    ) -> None: ...

    def complete_run(
        self,
        run_id: str,
        *,
        status: TriageRunStatus,
        completed_at: datetime,
    ) -> None: ...

    def recent(self, *, limit: int) -> list[TriageRunSummary]: ...

    def get(self, run_id: str) -> TriageRunDetails | None: ...

    def close(self) -> None: ...
