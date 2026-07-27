from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_edge_lab.application.ports.email import (
    EmailSourceError,
    EmailSourceFailureCategory,
)
from personal_edge_lab.application.ports.email_triage import NoOpTriageTraceSink
from personal_edge_lab.domain.ai import CompletionResult, CompletionTiming, ModelIdentity
from personal_edge_lab.domain.email import (
    EmailContentSource,
    EmailDocument,
    EmailItemFailure,
    EmailItemFailureCategory,
    EmailMessageId,
    EmailRetrievalBatch,
    EmailRetrievalRequest,
    EmailThreadId,
)
from personal_edge_lab.domain.email_triage_runs import (
    TriageRunItemStatus,
    TriageRunStatus,
)
from personal_edge_lab.infrastructure.ai.triage_decoder import (
    PydanticTriageDecisionDecoder,
)
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage import (
    SqliteTriageRunRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.email_triage.batch import TriageMailboxBatch
from personal_edge_lab.modules.email_triage.prompt import LocalTriagePromptSource
from personal_edge_lab.modules.email_triage.service import EmailTriageService

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class Source:
    def __init__(self, batch: EmailRetrievalBatch | EmailSourceError) -> None:
        self.batch = batch
        self.calls = 0

    def retrieve(self, request):
        self.calls += 1
        if isinstance(self.batch, EmailSourceError):
            raise self.batch
        assert request.limit <= 10
        return self.batch


class Model:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls = 0
        self.active = 0
        self.maximum_active = 0

    def complete(self, request):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            output = self.outputs[self.calls]
            self.calls += 1
            return CompletionResult(
                text=output,
                identity=ModelIdentity("llama_cpp", request.model_alias),
                usage=None,
                timing=CompletionTiming(0.1, 0.5),
            )
        finally:
            self.active -= 1


def _document(number: int, *, text: str = "Invoice amount due") -> EmailDocument:
    return EmailDocument(
        message_id=EmailMessageId(f"message-{number}"),
        thread_id=EmailThreadId(f"thread-{number}"),
        received_at=NOW,
        sender=f"sender-{number}@example.test",
        subject=f"Invoice {number}",
        text=text,
        content_source=EmailContentSource.PLAIN_TEXT,
        original_size_bytes=100,
        normalized_char_count=len(text),
    )


def _batch(
    documents: tuple[EmailDocument, ...],
    failures: tuple[EmailItemFailure, ...] = (),
) -> EmailRetrievalBatch:
    return EmailRetrievalBatch(
        documents=documents,
        failures=failures,
        next_cursor=None,
        pages_fetched=1,
        api_call_count=1 + len(documents) + len(failures),
        elapsed_seconds=0.2,
    )


def _service(model: Model) -> EmailTriageService:
    return EmailTriageService(
        model=model,
        prompt_source=LocalTriagePromptSource(),
        decoder=PydanticTriageDecisionDecoder(),
        trace_sink=NoOpTriageTraceSink(),
        model_alias="qwen3-1.7b-q4-k-m",
    )


def _execute(
    database,
    source: Source,
    model: Model,
    *,
    run_id: str,
    force: bool = False,
    interrupted=lambda: False,
):
    with SqliteTriageRunRepository(database) as repository:
        return TriageMailboxBatch(
            email_source=source,
            triage_service=_service(model),
            repository=repository,
            clock=lambda: NOW,
            interrupted=interrupted,
        ).execute(
            EmailRetrievalRequest("in:inbox", limit=3),
            run_id=run_id,
            operation_id=run_id,
            force_new_attempt=force,
        )


def test_successful_rerun_reuses_and_forced_run_calls_model_again(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    source = Source(_batch((_document(1),)))
    model = Model(
        [
            '{"label":"billing","reason":"Invoice"}',
            '{"label":"billing","reason":"Invoice again"}',
        ]
    )
    first = _execute(database, source, model, run_id="run-one")
    replay = _execute(database, source, model, run_id="run-two")
    forced = _execute(database, source, model, run_id="run-three", force=True)

    assert first.items[0].status is TriageRunItemStatus.SUCCEEDED
    assert replay.items[0].status is TriageRunItemStatus.REUSED
    assert replay.items[0].reason is None
    assert forced.items[0].status is TriageRunItemStatus.SUCCEEDED
    assert model.calls == 2
    assert model.maximum_active == 1


def test_partial_source_and_model_failures_are_durable_and_processing_continues(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    source = Source(
        _batch(
            (_document(1), _document(2)),
            (
                EmailItemFailure(
                    EmailItemFailureCategory.INVALID_MESSAGE,
                    message_id=EmailMessageId("message-bad"),
                ),
            ),
        )
    )
    model = Model(
        [
            '{"label":"billing","reason":"Invoice"}',
            "not-json",
        ]
    )
    result = _execute(database, source, model, run_id="partial-run")

    assert result.status is TriageRunStatus.COMPLETED_WITH_FAILURES
    assert [item.status for item in result.items] == [
        TriageRunItemStatus.FAILED,
        TriageRunItemStatus.SUCCEEDED,
        TriageRunItemStatus.FAILED,
    ]
    assert result.failure_count == 2
    assert model.calls == 2
    with SqliteTriageRunRepository(database) as repository:
        details = repository.get("partial-run")
    assert details is not None
    assert details.run.failed_count == 2
    assert details.run.succeeded_count == 1


def test_interruption_between_items_records_remaining_work_without_inference(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    source = Source(_batch((_document(1), _document(2))))
    model = Model([])
    result = _execute(
        database,
        source,
        model,
        run_id="interrupted-run",
        interrupted=lambda: True,
    )

    assert result.status is TriageRunStatus.INTERRUPTED
    assert all(item.status is TriageRunItemStatus.INTERRUPTED for item in result.items)
    assert model.calls == 0


def test_gmail_failure_is_recorded_before_items_and_re_raised(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    source = Source(
        EmailSourceError(
            "sanitized",
            category=EmailSourceFailureCategory.CONNECTION,
            retry_eligible=True,
        )
    )
    model = Model([])
    with pytest.raises(EmailSourceError):
        _execute(database, source, model, run_id="source-failure")
    with SqliteTriageRunRepository(database) as repository:
        details = repository.get("source-failure")
    assert details is not None
    assert details.run.status is TriageRunStatus.FAILED_BEFORE_ITEMS
    assert details.items == ()
