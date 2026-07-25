"""AC control application ports."""

from __future__ import annotations

from typing import Protocol

from personal_edge_lab.domain.ac import (
    AcState,
    CommandAuditEntry,
    CommandResult,
)


class AcController(Protocol):
    def set_state(self, state: AcState) -> CommandResult: ...

    def power_off(self) -> CommandResult: ...


class CommandAuditRepository(Protocol):
    def begin(self, *, device_id: str, command_type: str, payload_json: str) -> int: ...

    def complete(self, command_id: int, result: CommandResult) -> None: ...

    def history(self, *, limit: int) -> list[CommandAuditEntry]: ...
