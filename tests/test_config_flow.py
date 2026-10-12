from cube_test.config_flow import CubeConfigFlow
from homeassistant.data_entry_flow import FlowResultType


async def test_slow_connection_uses_background_progress():
    import asyncio

    flow = CubeConfigFlow()
    flow.flow_id = "test"
    flow.handler = "segway_cube"
    blocker = asyncio.Event()
    flow._connect_task = asyncio.create_task(blocker.wait())
    try:
        result = await flow.async_step_connect()
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        assert result["step_id"] == "connect"
        assert result["progress_task"] is flow._connect_task
        blocker.set()
        await flow._connect_task
        result = await flow.async_step_connect()
        assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
        assert result["step_id"] == "connection_result"
    finally:
        if flow._connect_task is not None:
            flow._connect_task.cancel()


async def test_credentials_form_does_not_default_to_stored_password():
    flow = CubeConfigFlow()
    flow.flow_id = "test"
    flow.handler = "segway_cube"
    flow._defaults = {"mac": "AA:BB:CC:DD:EE:FF", "password": "ab" * 16}
    result = await flow.async_step_user()
    assert "password" not in result.get("description_placeholders", {})
    password_field = next(k for k in result["data_schema"].schema if str(k) == "password")
    # Password fields have no default, even during reauthentication.
    import voluptuous as vol

    assert password_field.default is vol.UNDEFINED


async def test_pairing_prompt_keeps_connection_alive_and_cancel_stops_it():
    import asyncio

    flow = CubeConfigFlow()
    flow.flow_id, flow.handler = "test", "segway_cube"
    blocker = asyncio.Event()
    flow._connect_task = asyncio.create_task(blocker.wait())
    flow._progress_task = asyncio.create_task(flow._async_wait_for_pairing())
    result = await flow.async_step_connect()
    assert result["type"] == FlowResultType.SHOW_PROGRESS
    flow._pairing_ready.set()
    await flow._progress_task
    result = await flow.async_step_connect()
    assert result["step_id"] == "press_button"
    assert not flow._connect_task.done()
    result = await flow.async_step_press_button()
    assert result["progress_task"] is flow._connect_task
    flow.async_remove()
    await asyncio.gather(flow._connect_task, return_exceptions=True)
    assert flow._connect_task.cancelled()


async def test_confirmation_required_before_starting_pairing():
    flow = CubeConfigFlow()
    flow.flow_id, flow.handler = "test", "segway_cube"
    result = await flow.async_step_confirm_pairing({"confirm": False})
    assert result["errors"] == {"confirm": "confirmation_required"}
    assert flow._connect_task is None


async def test_journal_recovers_key_without_pairing_again(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from cube_test import config_flow as module

    key = "12" * 16
    journal = SimpleNamespace(get=AsyncMock(return_value={"serial": "SERIAL", "password": key}), save=AsyncMock())
    monkeypatch.setattr(module, "get_journal", lambda hass: journal)
    seen = {}

    class Client:
        def __init__(self, hass, address, name, password, profile):
            assert password.hex() == key
            self.password, self.name, self.profile, self.serial = password, name, profile, "SERIAL"
            self.last_probe = {}

        @asynccontextmanager
        async def session(self, **kwargs):
            seen.update(kwargs)
            yield SimpleNamespace(read=AsyncMock(return_value=bytes(2)))

    monkeypatch.setattr(module, "CubeClient", Client)
    flow = CubeConfigFlow()
    flow.hass = object()
    await flow._async_validate("AA:BB:CC:DD:EE:FF", None, {"pair": True, "ble_name": "Home"})
    assert seen["recovery"] and seen["expected_serial"] == "SERIAL"
    assert flow._validated["password"] == key
    journal.save.assert_not_called()


async def test_new_setup_reaches_confirmation_without_connecting(monkeypatch):
    from unittest.mock import AsyncMock

    flow = CubeConfigFlow()
    flow.flow_id, flow.handler = "test", "segway_cube"
    monkeypatch.setattr(flow, "async_set_unique_id", AsyncMock())
    monkeypatch.setattr(flow, "_abort_if_unique_id_configured", lambda: None)
    start = AsyncMock()
    monkeypatch.setattr(flow, "_async_start_validation", start)
    result = await flow.async_step_user({"mac": "AA:BB:CC:DD:EE:FF", "pair": True})
    assert result["step_id"] == "confirm_pairing"
    start.assert_not_called()
    assert flow._pending[1] is None
    await flow.async_step_confirm_pairing({"confirm": True})
    start.assert_awaited_once()


async def test_reconfiguration_keeps_key_without_echoing_it(monkeypatch):
    from unittest.mock import AsyncMock

    flow = CubeConfigFlow()
    flow.flow_id, flow.handler = "test", "segway_cube"
    flow.context = {"source": "reconfigure"}
    flow._defaults = {"mac": "AA:BB:CC:DD:EE:FF", "password": "13" * 16}
    monkeypatch.setattr(flow, "async_set_unique_id", AsyncMock())
    monkeypatch.setattr(flow, "_async_start_validation", AsyncMock(return_value={"step_id": "connect"}))
    result = await flow.async_step_user({"mac": "AA:BB:CC:DD:EE:FF", "pair": False})
    assert result["step_id"] == "connect"
    assert flow._pending[1] == bytes.fromhex("13" * 16)
