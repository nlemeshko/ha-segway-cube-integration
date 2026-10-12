from unittest.mock import AsyncMock

import pytest
from cube_test.client import Session
from cube_test.protocol import PairingRequired, PasswordRequired, ProtocolError, build_frame


def session():
    client = AsyncMock()
    return Session(client, "write", "notify", "gen2")


async def test_existing_binding_is_never_replaced_without_a_password():
    s = session()
    s.bound = True
    with pytest.raises(PasswordRequired):
        await s.authenticate(bytes(16), bytes(14), None, pair=True)
    s.client.write_gatt_char.assert_not_called()


async def test_unbound_station_requires_explicit_pairing():
    s = session()
    with pytest.raises(PairingRequired):
        await s.authenticate(bytes(16), bytes(14), None, pair=False)
    s.client.write_gatt_char.assert_not_called()


async def test_long_writes_are_fragmented_for_proxy_att_limit():
    s = session()
    await s.send(build_frame(18, 0x5D, 0, bytes(14)))
    chunks = [call.args[1] for call in s.client.write_gatt_char.call_args_list]
    assert [len(x) for x in chunks] == [20, 7]
    assert all(call.kwargs == {"response": False} for call in s.client.write_gatt_char.call_args_list)


async def test_responses_match_board_command_and_index():
    s = session()
    for board, command, index in [(18, 4, 48), (6, 5, 48), (6, 4, 49), (6, 4, 48)]:
        # Station response uses source-board then application BT ID.
        plain = bytes((0x5A, 0xA5, 2, board, 0x3E, command, index, 0x20, 0x03))
        s.queue.put_nowait(s.crypto.encrypt(plain))
    response = await s.receive(6, 4, 48, timeout=0.2)
    assert response.data == b"\x20\x03"


async def test_corrupt_response_is_not_used_as_telemetry():
    s = session()
    wire = bytearray(s.crypto.encrypt(bytes.fromhex("5aa502063e04302003")))
    wire[4] ^= 1
    s.queue.put_nowait(wire)
    with pytest.raises(ProtocolError, match="integrity"):
        await s.receive(6, 4, 48, timeout=0.2)


async def test_empty_queue_times_out():
    with pytest.raises(TimeoutError):
        await session().receive(6, 4, 48, timeout=0.01)


async def test_radio_failure_does_not_retry_all_encryption_profiles(monkeypatch):
    from bleak.exc import BleakError
    from cube_test import client as module

    monkeypatch.setattr(module.bluetooth, "async_ble_device_from_address", lambda *a, **kw: object())
    connect = AsyncMock(side_effect=BleakError("radio unavailable"))
    monkeypatch.setattr(module, "establish_connection", connect)
    c = module.CubeClient(object(), "AA:BB:CC:DD:EE:FF", "CubeTest")
    with pytest.raises(ProtocolError, match="Bluetooth connection failed"):
        async with c.session():
            pass
    assert connect.await_count == 1


async def test_confirmed_replacement_journals_before_write_and_retries_same_key(monkeypatch):
    from types import SimpleNamespace

    from cube_test import client as module

    s = session()
    s.name, s.serial, s.bound = "Home", "SERIAL", True
    key = bytes(range(16))
    monkeypatch.setattr(module.secrets, "token_bytes", lambda n: key)
    events = []

    async def save(serial, password, confirmed):
        assert serial == "SERIAL" and password == key
        events.append(("saved", confirmed))

    async def send(frame):
        events.append(("sent", frame[5], frame[7:]))

    s.send = send
    s.receive = AsyncMock(side_effect=[
        SimpleNamespace(index=0), TimeoutError(), SimpleNamespace(index=1), SimpleNamespace(index=1),
    ])
    await s.authenticate(bytes(16), bytes(14), None, True, replace=True, on_key=save,
                         on_pairing=lambda: events.append(("prompt",)))
    assert events[0] == ("saved", False)
    assert events[1] == ("prompt",)
    writes = [event for event in events if event[:2] == ("sent", 0x5C)]
    assert len(writes) == 2 and all(event[2] == key for event in writes)
    assert events.index(("saved", True)) < next(i for i, e in enumerate(events) if e[:2] == ("sent", 0x5D))
    assert s.password == key


async def test_failed_journal_does_not_write_new_key():
    s = session()
    s.send = AsyncMock()
    with pytest.raises(OSError):
        await s.authenticate(bytes(16), bytes(14), None, True, on_key=AsyncMock(side_effect=OSError()))
    s.send.assert_not_called()


async def test_rejected_pairing_does_not_authenticate():
    from types import SimpleNamespace

    s = session()
    s.send = AsyncMock()
    s.receive = AsyncMock(return_value=SimpleNamespace(index=2))
    save = AsyncMock()
    with pytest.raises(PairingRequired):
        await s.authenticate(bytes(16), bytes(14), None, True, on_key=save)
    assert save.await_count == 1
    assert s.send.await_count == 1
    assert s.password is None


async def test_button_timeout_retains_candidate_without_authentication(monkeypatch):
    from cube_test import client as module

    # Advance only the pairing loop clock, keeping asyncio's own clock intact.
    clock = iter([0, 0, 0, 0, 61])
    class Clock:
        def time(self):
            return next(clock)

    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: Clock())
    s = session()
    s.send = AsyncMock()
    s.receive = AsyncMock(side_effect=TimeoutError())
    save = AsyncMock()
    with pytest.raises(PairingRequired, match="timed out"):
        await s.authenticate(bytes(16), bytes(14), None, True, on_key=save)
    assert save.await_count == 1 and save.await_args.args[2] is False
    assert s.send.await_count == 1


async def test_setting_write_waits_for_readback_without_repeating_command(monkeypatch):
    from cube_test import client as module

    s = session()
    s.send = AsyncMock()
    s.read = AsyncMock(side_effect=[(700).to_bytes(2, "little"), (600).to_bytes(2, "little")])
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    assert await s.write_u16(0xD0, 600) == 600
    assert s.send.await_count == 1
    assert s.read.await_count == 2


async def test_setting_write_rejects_unconfirmed_value(monkeypatch):
    from cube_test import client as module

    s = session()
    s.send = AsyncMock()
    s.read = AsyncMock(return_value=(700).to_bytes(2, "little"))
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    with pytest.raises(ProtocolError, match="did not confirm"):
        await s.write_u16(0xD0, 600)
    assert s.send.await_count == 1 and s.read.await_count == 3
