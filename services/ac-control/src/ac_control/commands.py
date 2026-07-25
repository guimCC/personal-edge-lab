"""Command execution and audit orchestration."""

from __future__ import annotations

from collections.abc import Callable

from ac_control.client import AcCommandClient
from ac_control.models import (
    AcState,
    CommandExecution,
    CommandOutcome,
    CommandResult,
    canonical_json,
)
from ac_control.storage import CommandAuditStore


class CommandService:
    def __init__(
        self,
        *,
        device_id: str,
        client: AcCommandClient,
        store: CommandAuditStore,
    ) -> None:
        self._device_id = device_id
        self._client = client
        self._store = store

    def set_state(self, state: AcState) -> CommandExecution:
        return self._execute(
            command_type="set_state",
            payload_json=state.to_json(),
            send=lambda: self._client.set_state(state),
        )

    def power_off(self) -> CommandExecution:
        return self._execute(
            command_type="power_off",
            payload_json=canonical_json({"power": False}),
            send=self._client.power_off,
        )

    def reject(
        self,
        *,
        command_type: str,
        attempted_payload: dict[str, object],
        message: str,
    ) -> CommandExecution:
        payload_json = canonical_json(attempted_payload)
        result = CommandResult(
            outcome=CommandOutcome.REJECTED_LOCALLY,
            error_category="validation_error",
            error_message=message,
        )
        command_id = self._store.begin(
            device_id=self._device_id,
            command_type=command_type,
            payload_json=payload_json,
        )
        self._store.complete(command_id, result)
        return CommandExecution(command_id, command_type, payload_json, result)

    def _execute(
        self,
        *,
        command_type: str,
        payload_json: str,
        send: Callable[[], CommandResult],
    ) -> CommandExecution:
        command_id = self._store.begin(
            device_id=self._device_id,
            command_type=command_type,
            payload_json=payload_json,
        )
        result = send()
        self._store.complete(command_id, result)
        return CommandExecution(command_id, command_type, payload_json, result)
