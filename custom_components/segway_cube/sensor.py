"""Named power sensors and complete raw register sensors."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
)

from .entity import CubeEntity
from .registers import REGISTERS


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [CubeRegisterSensor(coordinator, r) for r in REGISTERS if coordinator.active_register(r)]
        + [CubeSignalSensor(coordinator)]
        + [CubeStatusSensor(coordinator, kind) for kind in ("battery", "temperature", "battery_modules")]
    )


class CubeRegisterSensor(CubeEntity, SensorEntity):
    def __init__(self, coordinator, register):
        super().__init__(coordinator, register.key)
        self.register = register
        self._attr_name = register.key
        if register.key in ("rInputPower", "rOutputPower"):
            self._attr_name = "Input power" if register.key == "rInputPower" else "Output power"
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
        else:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = register.dynamic or register.key in (
                "rBmsCycleCount",
                "rACInputPowerLimit",
            )

    @property
    def available(self):
        return super().available and self.register.key in (self.coordinator.data or {})

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.register.key)

    @property
    def extra_state_attributes(self):
        return {
            "board": f"0x{self.register.board:02X}",
            "register": f"0x{self.register.index:02X}",
            "raw_hex": self.coordinator.raw.get(self.register.key),
            "encoding": "unsigned little-endian" if self.register.length in (2, 4) else "ASCII or hex",
            "format_verified": self.register.key in ("rInputPower", "rOutputPower"),
        }


class CubeStatusSensor(CubeEntity, SensorEntity):
    """Useful values from the status fields verified against this Cube's display."""

    def __init__(self, coordinator, kind):
        super().__init__(coordinator, kind)
        self.kind = kind
        self._attr_translation_key = kind
        if kind == "battery":
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif kind == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_state_class = SensorStateClass.MEASUREMENT
        else:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        if self.kind == "battery_modules":
            return self.coordinator.battery_count
        value = (self.coordinator.data or {}).get("rSocTemp")
        if value is None:
            return None
        if self.kind == "battery":
            percent = value & 0xFF
            return percent if percent <= 100 else None
        temperature = (value >> 8) & 0xFF
        return temperature if temperature < 128 else temperature - 256


class CubeSignalSensor(CubeEntity, SensorEntity):
    _attr_name = "Bluetooth signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "rssi")

    @property
    def native_value(self):
        return self.coordinator.client.rssi()
