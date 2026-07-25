from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_edge_lab.application.ports.telemetry import SourceFailureCategory
from personal_edge_lab.domain.telemetry import CollectionAttemptOutcome
from personal_edge_lab.infrastructure.persistence.sqlite.collector_status import (
    SqliteCollectorStatusRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)


def test_collector_status_lifecycle_preserves_last_failure(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(minutes=5))
        repository.record_failure(
            "node-1",
            attempted_at=NOW - timedelta(seconds=20),
            category=SourceFailureCategory.TIMEOUT,
            message="temperature request timed out",
        )
        failed = repository.latest("node-1")
        repository.record_success("node-1", attempted_at=NOW - timedelta(seconds=5))
        recovered = repository.latest("node-1")
        repository.stop("node-1", stopped_at=NOW)
        stopped = repository.latest("node-1")

    assert failed is not None
    assert failed.last_attempt_outcome is CollectionAttemptOutcome.FAILURE
    assert failed.consecutive_failures == 1
    assert recovered is not None
    assert recovered.last_attempt_outcome is CollectionAttemptOutcome.SUCCESS
    assert recovered.consecutive_failures == 0
    assert recovered.last_failure_category == "timeout"
    assert recovered.last_failure_message == "temperature request timed out"
    assert stopped is not None
    assert stopped.stopped_at == NOW


def test_collector_restart_retains_historical_success_and_failure(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with SqliteCollectorStatusRepository(database) as repository:
        repository.start("node-1", started_at=NOW - timedelta(hours=1))
        repository.record_success("node-1", attempted_at=NOW - timedelta(minutes=1))
        repository.record_failure(
            "node-1",
            attempted_at=NOW - timedelta(seconds=30),
            category=SourceFailureCategory.CONNECTION,
            message="temperature node connection failed",
        )
        repository.start("node-1", started_at=NOW)
        status = repository.latest("node-1")

    assert status is not None
    assert status.process_started_at == NOW
    assert status.last_success_at == NOW - timedelta(minutes=1)
    assert status.last_failure_category == "connection"
    assert status.consecutive_failures == 0
