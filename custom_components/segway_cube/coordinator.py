"""Serialize reads and control; release proxy connection between polls."""

import asyncio
import logging
import time
from datetime import timedelta

from bleak.exc import BleakError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CubeClient
from .const import CONF_ALLOW_CONTROL, DEFAULT_DETAIL_INTERVAL, DEFAULT_INTERVAL
from .controls import CONTROL_REGISTERS, CONTROLS
from .protocol import PasswordRequired, ProtocolError
from .registers import BY_KEY, REGISTERS, WRITABLE, battery_count_from_raw

_LOGGER = logging.getLogger(__name__)
STARTUP_KEYS = {"rInputPower", "rOutputPower", "rSocTemp", "rBmsCount"}
DETAIL_BATCH_SIZE = 8


class CubeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CubeClient):
        super().__init__(
            hass,
            _LOGGER,
            name="Segway Cube",
            config_entry=entry,
            update_interval=timedelta(seconds=entry.options.get("scan_interval", DEFAULT_INTERVAL)),
        )
        self.client = client
        self.lock = asyncio.Lock()
        self.raw = {}
        self.failures = {}
        self.battery_count = None
        self.last_detail = 0.0
        self.poll_count = 0
        self._detail_pending = []

    def active_register(self, register):
        if self.battery_count is not None:
            if register.module.startswith("bms") and int(register.module[3:]) > self.battery_count:
                return False
            if register.key.startswith("rBms") and register.key.endswith("V") and register.key[4:5].isdigit():
                return int(register.key[4]) <= self.battery_count
        return True

    async def _async_update_data(self):
        async with self.lock:
            initial = self.poll_count == 0
            due = time.monotonic() - self.last_detail >= self.config_entry.options.get(
                "detail_interval", DEFAULT_DETAIL_INTERVAL
            )
            if not initial and not self._detail_pending and due:
                self._detail_pending = sorted(
                    (r for r in REGISTERS if not r.dynamic),
                    key=lambda r: (r.key != "rFunSupBool", r.key not in CONTROL_REGISTERS),
                )
            batch = [] if initial else self._detail_pending[:DETAIL_BATCH_SIZE]
            dynamic = [r for r in REGISTERS if r.dynamic and (not initial or r.key in STARTUP_KEYS)]
            ordered = sorted(
                dynamic + batch,
                key=lambda r: (
                    r.key != "rBmsCount",
                    r.key not in STARTUP_KEYS,
                    r.key not in CONTROL_REGISTERS and r.key != "rFunSupBool",
                ),
            )
            data = dict(self.data or {})
            successful = set()
            dynamic_success = 0
            link_error = None
            try:
                async with self.client.session() as session:
                    for register in ordered:
                        if not self.active_register(register):
                            if register in self._detail_pending:
                                self._detail_pending.remove(register)
                            continue
                        try:
                            raw = await session.read(register.board, register.index, register.length)
                            self.raw[register.key] = raw.hex()
                            data[register.key] = register.decode(raw)
                            self.failures.pop(register.key, None)
                            successful.add(register.key)
                            if register.dynamic:
                                dynamic_success += 1
                            if register.key == "rBmsCount":
                                self.battery_count = battery_count_from_raw(raw)
                        except (TimeoutError, ProtocolError) as err:
                            data.pop(register.key, None)
                            self.raw.pop(register.key, None)
                            self.failures[register.key] = str(err) or type(err).__name__
                            _LOGGER.debug("Cube %s unavailable: %s", register.key, type(err).__name__)
                        if register in self._detail_pending:
                            self._detail_pending.remove(register)
            except PasswordRequired as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (BleakError, TimeoutError, ProtocolError) as err:
                if not dynamic_success:
                    raise UpdateFailed(str(err)) from err
                link_error = err
                # Keep verified readings from this session, while removing
                # dynamic values that were not refreshed before the link ended.
                for register in dynamic:
                    if register.key not in successful:
                        data.pop(register.key, None)
                        self.raw.pop(register.key, None)
                        self.failures[register.key] = "Bluetooth connection ended before a current reading"
                _LOGGER.debug("Cube returned partial telemetry: %s", type(err).__name__)
            if not dynamic_success:
                raise UpdateFailed("No current telemetry received")
            if batch and not self._detail_pending and link_error is None:
                self.last_detail = time.monotonic()
            self.poll_count += 1
            return data

    async def set_register(self, key: str, value: int):
        if not self.config_entry.options.get(CONF_ALLOW_CONTROL, False):
            raise HomeAssistantError("Enable experimental control in the integration options first")
        if key not in WRITABLE or type(value) is not int or not 0 <= value <= 65535:
            raise HomeAssistantError("Unsupported setting or value")
        typed = next(
            (definition for definition in CONTROLS.values() if definition.register == key and not definition.mask), None
        )
        if typed is not None:
            choices = typed.choices(self.data or {})
            option = next((option for option, raw in choices.items() if raw == value), None)
            if option is None:
                raise HomeAssistantError("Unsupported value for this Cube")
            return await self.set_control(typed.key, option)
        async with self.lock:
            try:
                async with self.client.session() as session:
                    await session.write_u16(WRITABLE[key], value)
                data = dict(self.data or {})
                data[key] = value
                self.raw[key] = value.to_bytes(2, "little").hex()
                self.async_set_updated_data(data)
            except (BleakError, TimeoutError, ProtocolError) as err:
                raise HomeAssistantError(str(err)) from err

    async def set_control(self, key, value):
        definition = CONTROLS.get(key)
        if definition is None:
            raise HomeAssistantError("Unknown Cube setting")
        if key in {"ac_output", "dc_output", "r_drive", "ups", "button_tone"}:
            if type(value) is not bool:
                raise HomeAssistantError("Switch values must be boolean")
        elif not isinstance(value, str):
            raise HomeAssistantError("Choose one of the supported setting values")
        async with self.lock:
            try:
                async with self.client.session() as session:
                    data = dict(self.data or {})
                    if definition.support_mask or key == "ac_charge_limit":
                        data["rFunSupBool"] = int.from_bytes(await session.read(6, 0x2B), "little")
                    if not definition.supported(data):
                        raise HomeAssistantError("This Cube does not support the requested setting")
                    if definition.options or key == "ac_charge_limit":
                        choices = definition.choices(data)
                        if value not in choices:
                            raise HomeAssistantError("Unsupported value for this Cube")
                        desired = choices[value]
                    else:
                        desired = definition.mask if value else 0
                    register = BY_KEY[definition.register]
                    if definition.mask:
                        # Use a fresh read, never the cached poll value. Preserve
                        # every other bit, including unknown device features.
                        current = int.from_bytes(await session.read(6, register.index), "little")
                        desired = (current & ~definition.mask) | desired
                    await session.write_u16(register.index, desired)
                    data[definition.register] = desired
                    self.raw[definition.register] = desired.to_bytes(2, "little").hex()
                    self.failures.pop(definition.register, None)
                    if "rFunSupBool" in data:
                        self.raw["rFunSupBool"] = data["rFunSupBool"].to_bytes(2, "little").hex()
                self.async_set_updated_data(data)
            except PasswordRequired as err:
                self.config_entry.async_start_reauth(self.hass)
                raise HomeAssistantError("Bluetooth key rejected; reauthenticate the Cube") from err
            except (BleakError, TimeoutError, ProtocolError) as err:
                raise HomeAssistantError(str(err)) from err
