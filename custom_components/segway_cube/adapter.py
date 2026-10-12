"""Restrict HA's connection routing to one adapter without changing global state."""

from bleak.exc import BleakError
from habluetooth.usage import HaBleakClientWithServiceCache


class SourceLockedBleakClient(HaBleakClientWithServiceCache):
    def __init__(self, device, *args, cube_source, **kwargs):
        super().__init__(device, *args, **kwargs)
        self._cube_source = cube_source
        self._cube_address = device.address
        if not hasattr(self, "_async_get_backend_for_ble_device"):
            raise BleakError("This HA Bluetooth version cannot enforce an adapter lock")

    def _async_get_best_available_backend_and_device(self, manager):
        # HA's wrapper normally ignores the initial BLEDevice's source and
        # scores every route. Override selection for this client only, so
        # retries cannot escape the user's chosen adapter.
        for candidate in manager.async_scanner_devices_by_address(self._cube_address, True):
            if candidate.scanner.source != self._cube_source:
                continue
            backend = self._async_get_backend_for_ble_device(manager, candidate.scanner, candidate.ble_device)
            if backend is not None:
                return backend
            raise BleakError("No available connection slot on the selected Bluetooth adapter")
        raise BleakError("Cube is unavailable through the selected Bluetooth adapter")
