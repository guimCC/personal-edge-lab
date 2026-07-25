"""AC control application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from personal_edge_lab.domain.ac import (
    AcState,
    CommandAuditEntry,
    CommandRequestContext,
    CommandReservation,
    CommandResult,
)


class AcController(Protocol):
    def set_state(self, state: AcState) -> CommandResult: ...

    def power_off(self) -> CommandResult: ...


class CommandAuditRepository(Protocol):
    def begin(self, *, device_id: str, command_type: str, payload_json: str) -> int: ...

    def complete(self, command_id: int, result: CommandResult) -> None: ...

    def history(self, *, limit: int) -> list[CommandAuditEntry]: ...

    def get(self, command_id: int) -> CommandAuditEntry | None: ...

    def reserve(
        self,
        *,
        device_id: str,
        command_type: str,
        payload_json: str,
        request_fingerprint: str,
        context: CommandRequestContext,
        requested_at: datetime,
        requires_device_lock: bool,
    ) -> CommandReservation: ...
