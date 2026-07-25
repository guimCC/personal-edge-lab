"""AC command validation, execution, idempotency, and audit orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from personal_edge_lab.application.ports.ac import (
    AcController,
    CommandAuditRepository,
)
from personal_edge_lab.domain.ac import (
    AcState,
    CommandAuditEntry,
    CommandExecution,
    CommandOutcome,
    CommandRequestContext,
    CommandReservationStatus,
    CommandResult,
    canonical_json,
)


class CommandConflictError(RuntimeError):
    """Raised when an idempotency key is reused with another payload."""


class CommandInProgressError(RuntimeError):
    """Raised when the same command is still being processed."""


class DeviceBusyError(RuntimeError):
    """Raised when another dashboard command holds the device lease."""


class CommandRateLimitedError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("command rate limit exceeded")
        self.retry_after_seconds = max(1, retry_after_seconds)


class CommandService:
    def __init__(
        self,
        *,
        device_id: str,
        controller: AcController,
        audit_repository: CommandAuditRepository,
        context: CommandRequestContext | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._device_id = device_id
        self._controller = controller
        self._audit_repository = audit_repository
        self._context = context
        self._clock = clock

    def set_state(self, state: AcState) -> CommandExecution:
        return self._execute(
            command_type="set_state",
            payload_json=state.to_json(),
            send=lambda: self._controller.set_state(state),
        )

    def power_off(self) -> CommandExecution:
        return self._execute(
            command_type="power_off",
            payload_json=canonical_json({"power": False}),
            send=self._controller.power_off,
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
        command_id, replay = self._start(
            command_type=command_type,
            payload_json=payload_json,
            requires_device_lock=False,
        )
        if replay is not None:
            return replay
        self._audit_repository.complete(command_id, result)
        return CommandExecution(command_id, command_type, payload_json, result)

    def _execute(
        self,
        *,
        command_type: str,
        payload_json: str,
        send: Callable[[], CommandResult],
    ) -> CommandExecution:
        command_id, replay = self._start(
            command_type=command_type,
            payload_json=payload_json,
            requires_device_lock=True,
        )
        if replay is not None:
            return replay
        result = send()
        self._audit_repository.complete(command_id, result)
        return CommandExecution(command_id, command_type, payload_json, result)

    def _start(
        self,
        *,
        command_type: str,
        payload_json: str,
        requires_device_lock: bool,
    ) -> tuple[int, CommandExecution | None]:
        if self._context is None:
            return (
                self._audit_repository.begin(
                    device_id=self._device_id,
                    command_type=command_type,
                    payload_json=payload_json,
                ),
                None,
            )

        fingerprint = hashlib.sha256(
            canonical_json({"command_type": command_type, "payload": payload_json}).encode("utf-8")
        ).hexdigest()
        reservation = self._audit_repository.reserve(
            device_id=self._device_id,
            command_type=command_type,
            payload_json=payload_json,
            request_fingerprint=fingerprint,
            context=self._context,
            requested_at=self._clock(),
            requires_device_lock=requires_device_lock,
        )
        if reservation.status is CommandReservationStatus.CONFLICT:
            raise CommandConflictError("idempotency key already used for another command")
        if reservation.status is CommandReservationStatus.IN_PROGRESS:
            raise CommandInProgressError("command is already in progress")
        if reservation.status is CommandReservationStatus.DEVICE_BUSY:
            raise DeviceBusyError("another command is already in progress")
        if reservation.status is CommandReservationStatus.RATE_LIMITED:
            raise CommandRateLimitedError(reservation.retry_after_seconds or 1)
        if reservation.status is CommandReservationStatus.REPLAYED:
            if reservation.entry is None:
                raise RuntimeError("replayed reservation did not include an audit entry")
            return reservation.entry.id, _execution_from_entry(reservation.entry)
        if reservation.command_id is None:
            raise RuntimeError("new reservation did not include a command ID")
        return reservation.command_id, None


def _execution_from_entry(entry: CommandAuditEntry) -> CommandExecution:
    return CommandExecution(
        command_id=entry.id,
        command_type=entry.command_type,
        payload_json=entry.command_payload_json,
        result=CommandResult(
            outcome=entry.outcome,
            http_status=entry.http_status,
            response_body=entry.response_body,
            error_category=entry.error_category,
            error_message=entry.error_message,
        ),
        replayed=True,
    )
