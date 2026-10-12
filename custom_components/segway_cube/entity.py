"""Shared entity metadata."""

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class CubeEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.client.address)},
            manufacturer="Segway",
            model="Cube",
            name="Segway Cube " + coordinator.client.name,
            serial_number=coordinator.client.serial or None,
        )
