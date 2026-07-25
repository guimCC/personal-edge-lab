from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_edge_lab.domain.ac import CommandAuditEntry, CommandOutcome, CommandResult
from personal_edge_lab.modules.ac_control import CommandHistoryQueryError, ListCommandHistory


def entry(command_id: int) -> CommandAuditEntry:
    return CommandAuditEntry(
        id=command_id,
        device_id="node-1",
        command_type="power_off",
        command_payload_json='{"power":false}',
        requested_at_utc=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
        completed_at_utc=None,
        outcome=CommandOutcome.PENDING,
        http_status=None,
        response_body=None,
        error_category=None,
        error_message=None,
    )


class Repository:
    def __init__(self) -> None:
        self.entries = [entry(2), entry(1)]
        self.limit: int | None = None

    def begin(
        self,
        *,
        device_id: str,
        command_type: str,
        payload_json: str,
        requested_at: datetime,
    ) -> int:
        return 1

    def complete(
        self,
        command_id: int,
        result: CommandResult,
        *,
        completed_at: datetime,
    ) -> None:
        pass

    def history(self, *, limit: int) -> list[CommandAuditEntry]:
        self.limit = limit
        return self.entries[:limit]


def test_command_history_returns_domain_entries() -> None:
    repository = Repository()
    assert ListCommandHistory(repository).execute(limit=1) == [repository.entries[0]]
    assert repository.limit == 1


@pytest.mark.parametrize("limit", [0, 101])
def test_command_history_rejects_out_of_range_limit(limit: int) -> None:
    with pytest.raises(CommandHistoryQueryError, match="1 through 100"):
        ListCommandHistory(Repository()).execute(limit=limit)
