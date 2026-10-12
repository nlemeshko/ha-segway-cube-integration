"""Local Segway Cube Bluetooth integration."""

import asyncio

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .client import CubeClient
from .const import CONF_BLE_NAME, CONF_PROFILE, CONF_SOURCE, DOMAIN
from .coordinator import CubeCoordinator
from .protocol import parse_password
from .registers import WRITABLE

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SWITCH, Platform.SELECT]
STARTUP_TIMEOUT = 25
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = CubeClient(
        hass,
        entry.data[CONF_MAC],
        entry.data.get(CONF_BLE_NAME, ""),
        parse_password(entry.data.get(CONF_PASSWORD, "")),
        entry.data.get(CONF_PROFILE, "auto"),
        source=entry.options.get(CONF_SOURCE, "auto"),
    )
    coordinator = CubeCoordinator(hass, entry, client)
    try:
        async with asyncio.timeout(STARTUP_TIMEOUT):
            await coordinator.async_config_entry_first_refresh()
    except TimeoutError as err:
        # A connection retry must not hold the config flow HTTP request open
        # long enough for its cancellation to roll back the new entry.
        raise ConfigEntryNotReady("Bluetooth connection timed out; will retry in the background") from err
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    async def set_setting(call: ServiceCall):
        target = hass.config_entries.async_get_entry(call.data["entry_id"])
        if target is None or target.domain != DOMAIN or not hasattr(target, "runtime_data"):
            raise HomeAssistantError("Cube integration is not loaded")
        await target.runtime_data.set_register(call.data["setting"], call.data["value"])
        return {"setting": call.data["setting"], "value": call.data["value"], "confirmed": True}

    if not hass.services.has_service(DOMAIN, "set_setting"):
        hass.services.async_register(
            DOMAIN,
            "set_setting",
            set_setting,
            schema=vol.Schema(
                {
                    vol.Required("entry_id"): str,
                    vol.Required("setting"): vol.In(WRITABLE),
                    vol.Required("value"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
                }
            ),
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not any(
        e.entry_id != entry.entry_id and e.state.name == "LOADED" for e in hass.config_entries.async_entries(DOMAIN)
    ):
        hass.services.async_remove(DOMAIN, "set_setting")
    return unloaded
