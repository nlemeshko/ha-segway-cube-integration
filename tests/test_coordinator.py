import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from cube_test.coordinator import CubeCoordinator
from cube_test.registers import REGISTERS


def coordinator_for(session):
    @asynccontextmanager
    async def connection():
        yield session

    coordinator = CubeCoordinator.__new__(CubeCoordinator)
    coordinator.client = SimpleNamespace(session=connection)
    coordinator.config_entry = SimpleNamespace(options={})
    coordinator.lock = asyncio.Lock()
    coordinator.raw = {}
    coordinator.failures = {}
    coordinator.battery_count = None
    coordinator.last_detail = 0.0
    coordinator.poll_count = 0
    coordinator._detail_pending = []
    coordinator.data = None
    return coordinator


async def test_startup_succeeds_without_optional_registers_or_battery_count():
    class Station:
        async def read(self, board, index, length):
            if (board, index) == (6, 0xAA):
                raise TimeoutError
            if board == 6 and index in (0x30, 0x31, 0x32):
                return {0x30: b"\x02\x00", 0x31: b"\x00\x00", 0x32: b"\x64\x20"}[index]
            raise AssertionError("Startup probed an optional register")

    coordinator = coordinator_for(Station())
    data = await coordinator._async_update_data()
    assert data == {"rInputPower": 2, "rOutputPower": 0, "rSocTemp": 8292}
    assert coordinator.last_detail == 0
    assert coordinator.failures.keys() == {"rBmsCount"}


@pytest.mark.parametrize("count_raw, count", [(b"\x02\x00", 2), (b"\x03\x03", 3), (b"\x03\x04", None)])
async def test_full_catalogue_is_polled_after_startup_and_missing_batteries_are_skipped(count_raw, count):
    reads = []
    by_address = {(r.board, r.index): r for r in REGISTERS}

    class Station:
        async def read(self, board, index, length):
            register = by_address[board, index]
            reads.append(register)
            if register.key == "rBmsCount":
                return count_raw
            return bytes(length)

    coordinator = coordinator_for(Station())
    coordinator.data = await coordinator._async_update_data()
    reads.clear()
    coordinator.data = await coordinator._async_update_data()
    while coordinator._detail_pending:
        coordinator.data = await coordinator._async_update_data()
    data = coordinator.data
    assert "rBlePn" in data
    assert "rBattery2Info" in data
    assert coordinator.battery_count == count
    if count is not None:
        assert f"rBattery{count + 1}Info" not in data
        assert not any(r.module.startswith("bms") and int(r.module[3:]) > count for r in reads)
    else:
        # Unknown packed fields must never make us hide a possible battery.
        assert "rBattery5Info" in data
    assert coordinator.last_detail > 0


async def test_link_drop_preserves_current_values_and_retries_unread_detail():
    from bleak.exc import BleakError

    class Station:
        async def read(self, board, index, length):
            if board == 6 and index in (0xAA, 0x30, 0x31, 0x32):
                return bytes(length)
            raise BleakError("link ended")

    coordinator = coordinator_for(Station())
    coordinator.poll_count = 1
    coordinator.data = {"rFunBool2": 0x17, "rInputPower": 999}
    data = await coordinator._async_update_data()
    assert data["rInputPower"] == 0
    assert "rFunBool2" not in data
    assert coordinator._detail_pending
    assert coordinator.last_detail == 0
