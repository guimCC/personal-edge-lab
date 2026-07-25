"""Reusable authorization policies for non-CLI AC command channels."""

from __future__ import annotations

from collections.abc import Mapping

from personal_edge_lab.domain.ac import AcMode, AcState, CommandExecution, ValidationError
from personal_edge_lab.modules.ac_control.commands import CommandService

SET_STATE_FIELDS = {
    "power",
    "temperature_c",
    "mode",
    "fan",
    "vertical_vane",
}


class ExecuteCoolOnlyCommand:
    """Authorize the intentionally restricted command surface used by remote channels."""

    def __init__(self, service: CommandService) -> None:
        self._service = service

    def execute(
        self,
        *,
        command_type: str,
        state_payload: Mapping[str, object] | None,
    ) -> CommandExecution:
        attempted_payload: dict[str, object] = {"command_type": command_type}
        if state_payload is not None:
            attempted_payload["state"] = dict(state_payload)

        if command_type == "power_off":
            if state_payload is not None:
                return self._reject(
                    command_type,
                    attempted_payload,
                    "power_off must not include state",
                )
            return self._service.power_off()
        if command_type != "set_state":
            return self._reject(
                command_type,
                attempted_payload,
                "command_type must be set_state or power_off",
            )
        if state_payload is None:
            return self._reject(
                command_type,
                attempted_payload,
                "set_state requires state",
            )
        if set(state_payload) != SET_STATE_FIELDS:
            return self._reject(
                command_type,
                attempted_payload,
                "set_state requires exactly power, temperature_c, mode, fan, and vertical_vane",
            )
        try:
            state = AcState.from_values(
                power=state_payload.get("power"),
                temperature_c=state_payload.get("temperature_c"),
                mode=state_payload.get("mode"),
                fan=state_payload.get("fan"),
                vertical_vane=state_payload.get("vertical_vane"),
            )
            if not state.power:
                raise ValidationError("set_state requires power=true")
            if state.mode is not AcMode.COOL:
                raise ValidationError("remote controls currently authorize only cool mode")
        except ValidationError as error:
            return self._reject(command_type, attempted_payload, str(error))
        return self._service.set_state(state)

    def _reject(
        self,
        command_type: str,
        attempted_payload: dict[str, object],
        message: str,
    ) -> CommandExecution:
        return self._service.reject(
            command_type=command_type,
            attempted_payload=attempted_payload,
            message=message,
        )
