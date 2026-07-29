"""Resumable parent orchestration for a fixed twelve-month triage backfill."""

from __future__ import annotations

import calendar
import time
from collections.abc import Callable
from datetime import UTC, datetime

from personal_edge_lab.application.ports.email import EmailSource, EmailSourceError
from personal_edge_lab.application.ports.email_triage_backfill import (
    HistoricalEmailSource,
    TriageBackfillRepository,
)
from personal_edge_lab.domain.email import (
    EmailDocument,
    EmailRetrievalBatch,
    EmailRetrievalRequest,
)
from personal_edge_lab.domain.email_triage_backfill import (
    BACKFILL_MONTHS,
    TriageBackfillJob,
    TriageBackfillStatus,
    TriageBackfillStepResult,
    validate_backfill_step_items,
)
from personal_edge_lab.domain.email_triage_runs import TriageRunItemStatus
from personal_edge_lab.modules.email_triage.batch import TriageMailboxBatch

BACKFILL_SCOPE_EXCLUSIONS = "-in:sent -in:drafts -in:spam -in:trash -in:chats"


class TriageHistoricalBackfill:
    """Discover and process one bounded, operator-controlled unit of historical mail."""

    def __init__(
        self,
        *,
        email_source: HistoricalEmailSource,
        repository: TriageBackfillRepository,
        batch_factory: Callable[[EmailSource], TriageMailboxBatch],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.perf_counter,
        interrupted: Callable[[], bool] = lambda: False,
    ) -> None:
        self._email_source = email_source
        self._repository = repository
        self._batch_factory = batch_factory
        self._clock = clock
        self._monotonic = monotonic
        self._interrupted = interrupted

    def start(self, *, job_id: str, max_messages: int) -> TriageBackfillJob:
        cutoff = self._clock()
        segments = backfill_segments(cutoff)
        self._repository.create_job(
            job_id=job_id,
            starts_at=segments[-1][0],
            ends_at=cutoff,
            max_messages=max_messages,
            segments=segments,
            created_at=cutoff,
        )
        result = self._repository.get_job(job_id)
        assert result is not None
        return result

    def step(
        self,
        *,
        job_id: str,
        max_items: int,
        retry_failures: bool = False,
    ) -> TriageBackfillStepResult:
        validate_backfill_step_items(max_items)
        started = self._monotonic()
        now = self._clock()
        job = self._repository.get_job(job_id)
        if job is None:
            raise LookupError("backfill job not found")
        if job.status in {
            TriageBackfillStatus.COMPLETED,
            TriageBackfillStatus.COMPLETED_WITH_FAILURES,
            TriageBackfillStatus.CANCELLED,
        }:
            return TriageBackfillStepResult(job, 0, 0, 0, (), self._monotonic() - started)
        self._repository.recover_interrupted(job_id, recovered_at=now)
        if retry_failures:
            self._repository.retry_failures(job_id, updated_at=now)

        discovered_now = 0
        api_call_count = 0
        job = self._repository.get_job(job_id)
        assert job is not None
        segment = self._repository.active_segment(job_id)
        if (
            segment is not None
            and job.discovered_count < job.max_messages
            and not self._interrupted()
        ):
            request = EmailRetrievalRequest(
                query=backfill_query(segment.starts_at, segment.ends_at),
                limit=min(25, job.max_messages - job.discovered_count),
                cursor=segment.cursor,
            )
            discovery = self._email_source.discover(request)
            discovered_now = self._repository.record_discovery(
                job_id=job_id,
                segment_ordinal=segment.ordinal,
                message_ids=discovery.message_ids,
                next_cursor=(
                    discovery.next_cursor.value if discovery.next_cursor is not None else None
                ),
                updated_at=self._clock(),
            )
            api_call_count += discovery.api_call_count

        processed_now = 0
        child_run_ids: list[str] = []
        while processed_now < max_items and not self._interrupted():
            claimed = self._repository.claim_pending(
                job_id=job_id,
                limit=1,
                claimed_at=self._clock(),
            )
            if not claimed:
                break
            item_id, message_id, child_run_id = claimed[0]
            child_run_ids.append(child_run_id)
            try:
                document = self._email_source.retrieve_exact(message_id)
                api_call_count += 1
            except EmailSourceError as error:
                api_call_count += error.api_call_count
                self._repository.fail_item(
                    item_id=item_id,
                    category=error.category.value,
                    completed_at=self._clock(),
                )
                processed_now += 1
                continue
            if self._interrupted():
                self._repository.fail_item(
                    item_id=item_id,
                    category="interrupted",
                    completed_at=self._clock(),
                    interrupted=True,
                )
                break
            request = EmailRetrievalRequest(
                query=backfill_query(job.starts_at, job.ends_at),
                limit=1,
            )
            result = self._batch_factory(_SingleDocumentSource(document)).execute(
                request,
                run_id=child_run_id,
                operation_id=child_run_id,
            )
            item = result.items[0]
            if item.status in {TriageRunItemStatus.SUCCEEDED, TriageRunItemStatus.REUSED}:
                self._repository.complete_item(
                    item_id=item_id,
                    status=item.status.value,
                    child_run_id=child_run_id,
                    completed_at=self._clock(),
                )
            else:
                self._repository.fail_item(
                    item_id=item_id,
                    category=item.failure_category or item.status.value,
                    completed_at=self._clock(),
                    interrupted=item.status is TriageRunItemStatus.INTERRUPTED,
                )
            processed_now += 1

        if self._interrupted():
            self._repository.pause_job(job_id, updated_at=self._clock())
        job = self._repository.finalize_job(job_id, updated_at=self._clock())
        return TriageBackfillStepResult(
            job=job,
            discovered_now=discovered_now,
            processed_now=processed_now,
            api_call_count=api_call_count,
            child_run_ids=tuple(child_run_ids),
            elapsed_seconds=self._monotonic() - started,
        )


class _SingleDocumentSource:
    def __init__(self, document: EmailDocument) -> None:
        self._document = document

    def retrieve(self, request: EmailRetrievalRequest) -> EmailRetrievalBatch:
        del request
        return EmailRetrievalBatch(
            documents=(self._document,),
            failures=(),
            next_cursor=None,
            pages_fetched=0,
            api_call_count=0,
            elapsed_seconds=0,
        )


def backfill_segments(cutoff: datetime) -> tuple[tuple[datetime, datetime], ...]:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("backfill cutoff must be timezone-aware")
    boundaries = tuple(_subtract_months(cutoff, offset) for offset in range(BACKFILL_MONTHS + 1))
    return tuple((boundaries[index + 1], boundaries[index]) for index in range(BACKFILL_MONTHS))


def backfill_query(starts_at: datetime, ends_at: datetime) -> str:
    return (
        f"after:{int(starts_at.timestamp())} before:{int(ends_at.timestamp())} "
        f"{BACKFILL_SCOPE_EXCLUSIONS}"
    )


def _subtract_months(value: datetime, count: int) -> datetime:
    absolute_month = value.year * 12 + (value.month - 1) - count
    year, zero_based_month = divmod(absolute_month, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
