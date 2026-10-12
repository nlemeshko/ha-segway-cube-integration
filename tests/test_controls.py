import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cube_test.controls import CONTROLS, charge_limit
from cube_test.coordinator import CubeCoordinator
from cube_test.protocol import ProtocolError
from homeassistant.exceptions import HomeAssistantError


class Station:
    def __init__(self, capabilities=0xFEEE, flags=0x17):
        self.values = {0xC0: 0x02, 0xC1: flags, 0x2B: capabilities, 0xD0: 700}
        self.writes = []

    async def read(self, board, index, length=2):
        assert board == 6
        await asyncio.sleep(0)
        return self.values[index].to_bytes(length, "little")

    async def write_u16(self, index, value):
        self.writes.append((index, value))
        self.values[index] = value
        return value


def controller(station):
    c = CubeCoordinator.__new__(CubeCoordinator)

    @asynccontextmanager
    async def connection():
        yield station

    c.client = SimpleNamespace(session=connection)
    c.config_entry = SimpleNamespace(options={})
    c.lock = asyncio.Lock()
    # Stale cache: writing must use fresh station values instead.
    c.data = {"rFunBool2": 0, "rFunSupBool": 0x100}
    c.raw, c.failures = {}, {}

    def update(data):
        c.data = data

    c.async_set_updated_data = update
    return c


@pytest.mark.parametrize("capability,maximum", [(0x100, 1250), (0x200, 1650), (0, None), (0x300, None)])
def test_charging_choices_follow_reported_model(capability, maximum):
    data = {"rFunSupBool": capability}
    assert charge_limit(data) == maximum
    choices = CONTROLS["ac_charge_limit"].choices(data)
    if maximum:
        assert choices[f"{maximum} W"] == maximum
        assert maximum - 50 not in choices.values()
        assert min(choices.values()) == 200
    else:
        assert choices == {}


async def test_r_drive_preserves_unknown_bits_and_uses_fresh_read():
    station = Station(flags=0x8017)
    c = controller(station)
    await c.set_control("r_drive", False)
    assert station.writes == [(0xC1, 0x8013)]
    assert c.data["rFunBool2"] == 0x8013
    assert c.raw["rFunBool2"] == "1380"


async def test_concurrent_ups_and_button_tone_changes_preserve_each_other():
    station = Station()
    c = controller(station)
    await asyncio.gather(c.set_control("ups", False), c.set_control("button_tone", True))
    assert station.values[0xC1] == 0x1D
    assert len(station.writes) == 2


async def test_fan_select_preserves_other_features():
    station = Station()
    c = controller(station)
    await c.set_control("fan_mode", "silent")
    assert station.writes == [(0xC1, 0x07)]
    await c.set_control("fan_mode", "active_cooling")
    assert station.values[0xC1] == 0x17


async def test_charging_limit_checks_fresh_capabilities():
    station = Station(capabilities=0x200)
    c = controller(station)
    await c.set_control("ac_charge_limit", "1650 W")
    assert station.writes == [(0xD0, 1650)]
    assert c.data["rFunSupBool"] == 0x200
    with pytest.raises(HomeAssistantError):
        await c.set_control("ac_charge_limit", "1600 W")
    assert len(station.writes) == 1


async def test_unknown_charging_model_cannot_be_written():
    station = Station(capabilities=0)
    with pytest.raises(HomeAssistantError, match="does not support"):
        await controller(station).set_control("ac_charge_limit", "700 W")
    assert station.writes == []


async def test_frequency_switch_is_blocked_when_device_does_not_advertise_it():
    station = Station()
    with pytest.raises(HomeAssistantError, match="does not support"):
        await controller(station).set_control("ac_frequency", "60 Hz")
    assert station.writes == []


async def test_invalid_inputs_never_write():
    station = Station()
    c = controller(station)
    for key, value in [
        ("ups", 1),
        ("ups", "on"),
        ("fan_mode", "off"),
        ("screen_timeout", "12_hours"),
        ("firmwareReset", True),
    ]:
        with pytest.raises(HomeAssistantError):
            await c.set_control(key, value)
    assert station.writes == []


async def test_failed_readback_does_not_claim_success():
    station = Station()
    station.write_u16 = AsyncMock(side_effect=ProtocolError("readback mismatch"))
    c = controller(station)
    with pytest.raises(HomeAssistantError, match="readback mismatch"):
        await c.set_control("ups", False)
    assert c.data["rFunBool2"] == 0
    assert c.raw == {}


async def test_outputs_use_official_ac_dc_bits():
    station = Station()
    c = controller(station)
    await c.set_control("dc_output", True)
    assert station.values[0xC0] == 3
    await c.set_control("ac_output", False)
    assert station.values[0xC0] == 1
