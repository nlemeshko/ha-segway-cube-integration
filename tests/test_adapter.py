from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bleak.exc import BleakError
from cube_test.adapter import SourceLockedBleakClient
from cube_test.client import CubeClient
from cube_test.config_flow import source_options
from cube_test.protocol import ProtocolError

ADDRESS = "AA:BB:CC:DD:EE:FF"
SOURCE = "11:22:33:44:55:66"


def path(source):
    return SimpleNamespace(scanner=SimpleNamespace(source=source),
                           ble_device=SimpleNamespace(address=ADDRESS),
                           advertisement=SimpleNamespace(rssi=-60))


def locked():
    client = SourceLockedBleakClient.__new__(SourceLockedBleakClient)
    client._cube_source, client._cube_address = SOURCE, ADDRESS
    return client


def test_backend_selects_only_pinned_scanner_even_with_another_path(monkeypatch):
    client = locked()
    chosen = path(SOURCE)
    manager = SimpleNamespace(async_scanner_devices_by_address=lambda *a: [path("OTHER"), chosen])
    resolve = Mock(return_value="PINNED_BACKEND")
    monkeypatch.setattr(client, "_async_get_backend_for_ble_device", resolve)
    assert client._async_get_best_available_backend_and_device(manager) == "PINNED_BACKEND"
    resolve.assert_called_once_with(manager, chosen.scanner, chosen.ble_device)


def test_busy_pinned_adapter_never_falls_back_to_other(monkeypatch):
    client = locked()
    manager = SimpleNamespace(async_scanner_devices_by_address=lambda *a: [path(SOURCE), path("OTHER")])
    resolve = Mock(return_value=None)
    monkeypatch.setattr(client, "_async_get_backend_for_ble_device", resolve)
    with pytest.raises(BleakError, match="selected Bluetooth adapter"):
        client._async_get_best_available_backend_and_device(manager)
    assert resolve.call_count == 1


def test_missing_pinned_adapter_never_uses_other(monkeypatch):
    client = locked()
    manager = SimpleNamespace(async_scanner_devices_by_address=lambda *a: [path("OTHER")])
    resolve = Mock()
    monkeypatch.setattr(client, "_async_get_backend_for_ble_device", resolve)
    with pytest.raises(BleakError, match="unavailable"):
        client._async_get_best_available_backend_and_device(manager)
    resolve.assert_not_called()


async def test_missing_source_does_not_start_automatic_connection(monkeypatch):
    from cube_test import client as module

    monkeypatch.setattr(module.bluetooth, "async_scanner_devices_by_address", lambda *a, **kw: [path("OTHER")])
    connect = AsyncMock()
    monkeypatch.setattr(module, "establish_connection", connect)
    client = CubeClient(object(), ADDRESS, source=SOURCE)
    with pytest.raises(ProtocolError, match="Selected Bluetooth adapter"):
        async with client.session():
            pass
    connect.assert_not_called()
    assert client.rssi() is None


def test_source_options_keep_offline_selection_and_exclude_passive_adapters(monkeypatch):
    from cube_test import config_flow as module

    monkeypatch.setattr(module.bluetooth, "async_current_scanners", lambda hass: [
        SimpleNamespace(source="OTHER", name="bluetooth-1", connectable=True),
        SimpleNamespace(source="PASSIVE", name="passive receiver", connectable=False),
    ])
    options = source_options(SimpleNamespace(config=SimpleNamespace(language="ru")), SOURCE)
    assert [option["value"] for option in options] == ["auto", "OTHER", SOURCE]
    assert "недоступен" in options[-1]["label"]
