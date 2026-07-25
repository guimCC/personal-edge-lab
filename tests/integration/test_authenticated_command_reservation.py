from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from personal_edge_lab.domain.ac import (
    CommandOutcome,
    CommandRequestContext,
    CommandReservationStatus,
    CommandResult,
)
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
PAYLOAD = '{"power":false}'
FINGERPRINT = "f" * 64


def context(key: str) -> CommandRequestContext:
    return CommandRequestContext(
        actor_id="owner",
        request_source="dashboard",
        idempotency_key=key,
        rate_limit=6,
        rate_window_seconds=60,
        lock_lease_seconds=15,
    )


def reserve(database, key: str, requested_at: datetime = NOW):
    with SqliteCommandAuditRepository(database) as repository:
        return repository.reserve(
            device_id="node-1",
            command_type="power_off",
            payload_json=PAYLOAD,
            request_fingerprint=FINGERPRINT,
            context=context(key),
            requested_at=requested_at,
            requires_device_lock=True,
        )


def test_simultaneous_duplicate_has_exactly_one_new_reservation(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: reserve(
                    database,
                    "550e8400-e29b-41d4-a716-446655440000",
                ),
                range(2),
            )
        )

    assert {result.status for result in results} == {
        CommandReservationStatus.NEW,
        CommandReservationStatus.IN_PROGRESS,
    }
    assert len({result.command_id for result in results}) == 1


def test_device_lock_blocks_other_key_and_completed_result_replays(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    first = reserve(database, "550e8400-e29b-41d4-a716-446655440001")
    blocked = reserve(database, "550e8400-e29b-41d4-a716-446655440002")
    assert first.status is CommandReservationStatus.NEW
    assert blocked.status is CommandReservationStatus.DEVICE_BUSY

    assert first.command_id is not None
    with SqliteCommandAuditRepository(database) as repository:
        repository.complete(
            first.command_id,
            CommandResult(outcome=CommandOutcome.CONFIRMED_SUCCESS, http_status=200),
        )
    replay = reserve(database, "550e8400-e29b-41d4-a716-446655440001")
    assert replay.status is CommandReservationStatus.REPLAYED
    assert replay.entry is not None
    assert replay.entry.outcome is CommandOutcome.CONFIRMED_SUCCESS


def test_expired_lease_marks_interrupted_attempt_unknown_without_resending(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    first = reserve(database, "550e8400-e29b-41d4-a716-446655440003")
    recovered = reserve(
        database,
        "550e8400-e29b-41d4-a716-446655440004",
        requested_at=NOW + timedelta(seconds=15),
    )

    assert recovered.status is CommandReservationStatus.NEW
    assert first.command_id is not None
    with SqliteCommandAuditRepository(database) as repository:
        interrupted = repository.get(first.command_id)
    assert interrupted is not None
    assert interrupted.outcome is CommandOutcome.RESPONSE_UNKNOWN
    assert interrupted.error_category == "interrupted_unknown"


def test_expired_duplicate_replays_unknown_instead_of_staying_pending(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    key = "550e8400-e29b-41d4-a716-446655440005"
    first = reserve(database, key)
    recovered = reserve(
        database,
        key,
        requested_at=NOW + timedelta(seconds=15),
    )

    assert recovered.status is CommandReservationStatus.REPLAYED
    assert recovered.command_id == first.command_id
    assert recovered.entry is not None
    assert recovered.entry.outcome is CommandOutcome.RESPONSE_UNKNOWN
