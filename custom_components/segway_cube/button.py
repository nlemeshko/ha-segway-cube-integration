"""Manual refresh without changing station settings."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import CubeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CubeRefreshButton(entry.runtime_data)])


class CubeRefreshButton(CubeEntity, ButtonEntity):
    _attr_name = "Refresh all readings"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator):
        super().__init__(coordinator, "refresh")

    async def async_press(self):
        self.coordinator.last_detail = 0
        await self.coordinator.async_request_refresh()
