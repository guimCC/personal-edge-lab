from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from personal_edge_lab.application.ports.email_triage import NoOpTriageTraceSink
from personal_edge_lab.domain.ai import CompletionResult, CompletionTiming, ModelIdentity
from personal_edge_lab.domain.email import (
    EmailContentSource,
    EmailDocument,
    EmailMessageId,
    EmailThreadId,
)
from personal_edge_lab.domain.email_triage_backfill import (
    BACKFILL_MONTHS,
    TriageBackfillDiscoveryBatch,
    TriageBackfillValidationError,
    validate_backfill_step_items,
)
from personal_edge_lab.infrastructure.ai.triage_decoder import PydanticTriageDecisionDecoder
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage_backfill import (
    SqliteTriageBackfillRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.email_triage import EmailTriageService, TriageMailboxBatch
from personal_edge_lab.modules.email_triage.backfill import (
    BACKFILL_SCOPE_EXCLUSIONS,
    TriageHistoricalBackfill,
    backfill_query,
    backfill_segments,
)
from personal_edge_lab.modules.email_triage.prompt import LocalTriagePromptSource


def test_twelve_month_segments_are_contiguous_newest_first() -> None:
    cutoff = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)

    segments = backfill_segments(cutoff)

    assert len(segments) == BACKFILL_MONTHS
    assert segments[0][1] == cutoff
    assert segments[-1][0] == datetime(2025, 7, 29, 12, 30, tzinfo=UTC)
    assert all(segments[index][0] == segments[index + 1][1] for index in range(11))


def test_month_segments_clamp_end_of_month_without_gaps() -> None:
    cutoff = datetime(2026, 3, 31, 8, 0, tzinfo=UTC)

    segments = backfill_segments(cutoff)

    assert segments[0][0] == datetime(2026, 2, 28, 8, 0, tzinfo=UTC)
    assert segments[1][1] == segments[0][0]


def test_scope_query_uses_frozen_epoch_bounds_and_excludes_non_received_mail() -> None:
    start = datetime(2025, 7, 29, tzinfo=UTC)
    end = datetime(2026, 7, 29, tzinfo=UTC)

    query = backfill_query(start, end)

    assert query == (
        f"after:{int(start.timestamp())} before:{int(end.timestamp())} {BACKFILL_SCOPE_EXCLUSIONS}"
    )
    assert "-in:sent" in query
    assert "-in:trash" in query


@pytest.mark.parametrize("value", [0, 11, True])
def test_backfill_step_is_bounded(value) -> None:
    with pytest.raises(TriageBackfillValidationError):
        validate_backfill_step_items(value)


class _HistoricalSource:
    def __init__(self) -> None:
        self.discovery_calls = 0

    def discover(self, _request):
        self.discovery_calls += 1
        return TriageBackfillDiscoveryBatch(
            message_ids=(EmailMessageId("message-1"),),
            next_cursor=None,
            api_call_count=1,
            elapsed_seconds=0.1,
        )

    def retrieve_exact(self, message_id):
        text = "Recruiting opportunity"
        return EmailDocument(
            message_id=message_id,
            thread_id=EmailThreadId("thread-1"),
            received_at=datetime(2026, 6, 1, tzinfo=UTC),
            sender="recruiter@example.test",
            subject="Opportunity",
            text=text,
            content_source=EmailContentSource.PLAIN_TEXT,
            original_size_bytes=len(text),
            normalized_char_count=len(text),
        )


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return CompletionResult(
            text='{"label":"job","reason":"Recruiting opportunity"}',
            identity=ModelIdentity("llama_cpp", request.model_alias),
            usage=None,
            timing=CompletionTiming(0, 1),
        )


def test_backfill_reuses_existing_pipeline_and_deduplicates_discovery(
    tmp_path: Path,
) -> None:
    database = tmp_path / "backfill.db"
    run_migrations(database)
    source = _HistoricalSource()
    model = _Model()
    service = EmailTriageService(
        model=model,
        prompt_source=LocalTriagePromptSource(),
        decoder=PydanticTriageDecisionDecoder(),
        trace_sink=NoOpTriageTraceSink(),
        model_alias="qwen3-1.7b-q4-k-m",
    )
    with (
        SqliteTriageRunRepository(database) as runs,
        SqliteTriageBackfillRepository(database) as jobs,
    ):
        backfill = TriageHistoricalBackfill(
            email_source=source,
            repository=jobs,
            batch_factory=lambda email_source: TriageMailboxBatch(
                email_source=email_source,
                triage_service=service,
                repository=runs,
                clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            ),
            clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        )
        backfill.start(job_id="a" * 32, max_messages=100)
        first = backfill.step(job_id="a" * 32, max_items=1)
        second = backfill.step(job_id="a" * 32, max_items=1)

    assert first.processed_now == 1
    assert first.job.succeeded_count == 1
    assert second.discovered_now == 0
    assert second.processed_now == 0
    assert model.calls == 1
