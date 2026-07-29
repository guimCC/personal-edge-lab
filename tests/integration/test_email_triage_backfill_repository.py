from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from personal_edge_lab.domain.email import EmailMessageId
from personal_edge_lab.domain.email_triage_backfill import TriageBackfillStatus
from personal_edge_lab.infrastructure.persistence.sqlite.email_triage_backfill import (
    SqliteTriageBackfillRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.email_triage.backfill import backfill_segments

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _create(repository: SqliteTriageBackfillRepository, job_id: str = "a" * 32) -> None:
    segments = backfill_segments(NOW)
    repository.create_job(
        job_id=job_id,
        starts_at=segments[-1][0],
        ends_at=NOW,
        max_messages=3,
        segments=segments,
        created_at=NOW,
    )


def test_job_discovery_is_deduplicated_and_claims_are_durable(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageBackfillRepository(database) as repository:
        _create(repository)
        inserted = repository.record_discovery(
            job_id="a" * 32,
            segment_ordinal=1,
            message_ids=(
                EmailMessageId("message-1"),
                EmailMessageId("message-2"),
            ),
            next_cursor="cursor-2",
            updated_at=NOW,
        )
        duplicate = repository.record_discovery(
            job_id="a" * 32,
            segment_ordinal=1,
            message_ids=(EmailMessageId("message-1"),),
            next_cursor=None,
            updated_at=NOW,
        )
        claim = repository.claim_pending(job_id="a" * 32, limit=1, claimed_at=NOW)

    assert inserted == 2
    assert duplicate == 0
    assert claim[0][1] == EmailMessageId("message-1")
    assert len(claim[0][2]) == 32


def test_only_one_nonterminal_backfill_can_exist(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageBackfillRepository(database) as repository:
        _create(repository, "a" * 32)
        with pytest.raises(sqlite3.IntegrityError):
            _create(repository, "b" * 32)


def test_failure_retry_and_cancellation_are_explicit(tmp_path) -> None:
    database = tmp_path / "triage.db"
    run_migrations(database)
    with SqliteTriageBackfillRepository(database) as repository:
        _create(repository)
        repository.record_discovery(
            job_id="a" * 32,
            segment_ordinal=1,
            message_ids=(EmailMessageId("message-1"),),
            next_cursor=None,
            updated_at=NOW,
        )
        item_id, _message_id, _run_id = repository.claim_pending(
            job_id="a" * 32,
            limit=1,
            claimed_at=NOW,
        )[0]
        repository.fail_item(
            item_id=item_id,
            category="timeout",
            completed_at=NOW,
        )
        assert repository.get_job("a" * 32).failed_count == 1  # type: ignore[union-attr]
        assert repository.retry_failures("a" * 32, updated_at=NOW) == 1
        repository.cancel_job("a" * 32, updated_at=NOW)
        job = repository.get_job("a" * 32)

    assert job is not None
    assert job.status is TriageBackfillStatus.CANCELLED
    assert job.interrupted_count == 1
