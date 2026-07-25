from __future__ import annotations

import pytest

from ac_control.models import AcMode, AcState, FanSpeed, ValidationError, VerticalVane


def make_state(**overrides: object) -> AcState:
    values = {
        "power": "on",
        "temperature_c": "24",
        "mode": "cool",
        "fan": "auto",
        "vertical_vane": "middle",
    }
    values.update(overrides)
    return AcState.from_values(**values)


def test_valid_state_is_normalized_and_serialized() -> None:
    state = make_state()
    assert state == AcState(True, 24, AcMode.COOL, FanSpeed.AUTO, VerticalVane.MIDDLE)
    assert state.to_json() == (
        '{"fan":"auto","mode":"cool","power":true,"temperature_c":24,"vertical_vane":"middle"}'
    )


@pytest.mark.parametrize("temperature", ["16", "31"])
def test_temperature_contract_boundaries_are_supported(temperature: str) -> None:
    assert make_state(temperature_c=temperature).temperature_c == int(temperature)


@pytest.mark.parametrize("temperature", [None, "15", "32", "24.5", "warm", True])
def test_invalid_temperature_is_rejected(temperature: object) -> None:
    with pytest.raises(ValidationError, match="temperature"):
        make_state(temperature_c=temperature)


@pytest.mark.parametrize("mode", list(AcMode))
def test_every_mode_is_supported(mode: AcMode) -> None:
    assert make_state(mode=mode.value).mode is mode


@pytest.mark.parametrize("fan", list(FanSpeed))
def test_every_fan_speed_is_supported(fan: FanSpeed) -> None:
    assert make_state(fan=fan.value).fan is fan


@pytest.mark.parametrize("vane", list(VerticalVane))
def test_every_vertical_vane_is_supported(vane: VerticalVane) -> None:
    assert make_state(vertical_vane=vane.value).vertical_vane is vane


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("power", "standby", "power"),
        ("mode", "eco", "mode"),
        ("fan", "turbo", "fan"),
        ("vertical_vane", "left", "vertical-vane"),
    ],
)
def test_unsupported_field_value_is_rejected(field: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_state(**{field: value})


def test_missing_fields_are_reported_together() -> None:
    with pytest.raises(ValidationError, match=r"mode.*fan"):
        make_state(mode=None, fan=None)
