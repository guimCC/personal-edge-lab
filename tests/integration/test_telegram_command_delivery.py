from __future__ import annotations

from datetime import UTC, datetime

from personal_edge_lab.domain.ac import (
    AcState,
    CommandOutcome,
    CommandRequestContext,
    CommandResult,
)
from personal_edge_lab.infrastructure.persistence.sqlite.command_audit import (
    SqliteCommandAuditRepository,
)
from personal_edge_lab.infrastructure.persistence.sqlite.migrations import run_migrations
from personal_edge_lab.modules.ac_control import CommandService

NOW = datetime(2026, 7, 26, 21, 0, tzinfo=UTC)


class CountingController:
    def __init__(self) -> None:
        self.power_off_calls = 0

    def set_state(self, _state: AcState) -> CommandResult:
        raise AssertionError("set_state was not expected")

    def power_off(self) -> CommandResult:
        self.power_off_calls += 1
        return CommandResult(CommandOutcome.CONFIRMED_SUCCESS, http_status=200)


def test_replayed_telegram_confirmation_never_repeats_the_physical_request(tmp_path) -> None:
    database = tmp_path / "telemetry.db"
    run_migrations(database)
    controller = CountingController()
    context = CommandRequestContext(
        actor_id="telegram:112233",
        request_source="telegram_bot",
        idempotency_key="tg-1234567890abcdef1234",
        rate_limit=6,
        rate_window_seconds=60,
        lock_lease_seconds=15,
    )

    with SqliteCommandAuditRepository(database) as repository:
        first = CommandService(
            device_id="ac-controller-01",
            controller=controller,
            audit_repository=repository,
            context=context,
            clock=lambda: NOW,
        ).power_off()
    with SqliteCommandAuditRepository(database) as repository:
        replay = CommandService(
            device_id="ac-controller-01",
            controller=controller,
            audit_repository=repository,
            context=context,
            clock=lambda: NOW,
        ).power_off()
        entry = repository.get(first.command_id)

    assert controller.power_off_calls == 1
    assert replay.replayed is True
    assert replay.command_id == first.command_id
    assert entry is not None
    assert entry.actor_id == "telegram:112233"
    assert entry.request_source == "telegram_bot"
