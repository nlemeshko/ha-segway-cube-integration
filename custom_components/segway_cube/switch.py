"""AC/DC, R-Drive, UPS and button-tone switches."""

from homeassistant.components.switch import SwitchEntity

from .control_entity import CubeControlEntity, add_supported_controls
from .controls import SWITCHES


async def async_setup_entry(hass, entry, async_add_entities):
    add_supported_controls(entry, async_add_entities, SWITCHES, CubeSwitch)


class CubeSwitch(CubeControlEntity, SwitchEntity):
    @property
    def is_on(self):
        value = (self.coordinator.data or {}).get(self.definition.register)
        return bool(value & self.definition.mask) if value is not None else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_control(self.definition.key, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_control(self.definition.key, False)
