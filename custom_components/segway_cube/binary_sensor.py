"""Error and warning presence without guessing individual bit meanings."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import CubeEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            CubeProblemSensor(entry.runtime_data, "rErrorCode", "Error"),
            CubeProblemSensor(entry.runtime_data, "rWarnCode", "Warning"),
        ]
    )


class CubeProblemSensor(CubeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key + "_active")
        self.key = key
        self._attr_name = name

    @property
    def available(self):
        return super().available and self.key in (self.coordinator.data or {})

    @property
    def is_on(self):
        value = (self.coordinator.data or {}).get(self.key)
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self):
        return {"code": (self.coordinator.data or {}).get(self.key)}
