"""Discrete settings using the same choices as the official Cube app."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .control_entity import CubeControlEntity, add_supported_controls
from .controls import SELECTS


async def async_setup_entry(hass, entry, async_add_entities):
    add_supported_controls(entry, async_add_entities, SELECTS, CubeSelect)


class CubeSelect(CubeControlEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def options(self):
        return list(self.definition.choices(self.coordinator.data or {}))

    @property
    def current_option(self):
        data = self.coordinator.data or {}
        value = data.get(self.definition.register)
        if value is None:
            return None
        if self.definition.mask:
            value &= self.definition.mask
        return next((option for option, raw in self.definition.choices(data).items() if raw == value), None)

    async def async_select_option(self, option):
        await self.coordinator.set_control(self.definition.key, option)
