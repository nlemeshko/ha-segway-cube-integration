"""Discovery, credential validation, reauthentication and polling options."""

import asyncio
import logging
import re

import voluptuous as vol
from bleak.exc import BleakError
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_MAC, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import CubeClient
from .const import (
    CONF_ALLOW_CONTROL,
    CONF_BLE_NAME,
    CONF_PAIR,
    CONF_PROFILE,
    CONF_SOURCE,
    DEFAULT_DETAIL_INTERVAL,
    DEFAULT_INTERVAL,
    DOMAIN,
)
from .pairing import get_journal
from .protocol import PairingRequired, PasswordRequired, ProtocolError, is_cube, parse_password

_LOGGER = logging.getLogger(__name__)


@callback
def source_options(hass, selected="auto"):
    russian = hass.config.language == "ru"
    options = [{"value": "auto", "label": "Автоматически" if russian else "Automatic"}]
    for scanner in bluetooth.async_current_scanners(hass):
        if scanner.connectable:
            options.append({"value": scanner.source, "label": scanner.name})
    if selected != "auto" and selected not in {item["value"] for item in options}:
        options.append({"value": selected, "label": selected + (" (недоступен)" if russian else " (offline)")})
    return options


class CubeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._defaults = {}
        self._probe = {}
        self._connect_task = None
        self._errors = {}
        self._validated = None
        self._pending = None
        self._pairing_ready = asyncio.Event()
        self._progress_task = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CubeOptionsFlow()

    async def async_step_bluetooth(self, discovery_info: bluetooth.BluetoothServiceInfoBleak):
        if not is_cube(discovery_info.manufacturer_data):
            return self.async_abort(reason="not_cube")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._defaults = {CONF_MAC: discovery_info.address, CONF_BLE_NAME: discovery_info.name.rstrip("\x00")}
        self.context = {**self.context, "title_placeholders": {"name": "Segway Cube " + self._defaults[CONF_BLE_NAME]}}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data):
        self._defaults = dict(entry_data)
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input=None):
        if not self._defaults:
            self._defaults = dict(self._get_reconfigure_entry().data)
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        errors, self._errors = self._errors, {}
        if user_input is not None:
            user_input = dict(user_input)
            address = user_input[CONF_MAC].strip().upper()
            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_MAC] = "invalid_address"
            try:
                password = parse_password(user_input.get(CONF_PASSWORD, ""))
            except ValueError:
                errors[CONF_PASSWORD] = "invalid_password"
            if not errors:
                await self.async_set_unique_id(address)
                if self.source not in ("reauth", "reconfigure"):
                    self._abort_if_unique_id_configured()
                self._defaults.update({k: v for k, v in user_input.items() if k != CONF_PASSWORD})
                # Reconfiguration can keep the current secret without echoing it in a form.
                if password is None and not user_input.get(CONF_PAIR, False):
                    password = parse_password(self._defaults.get(CONF_PASSWORD, ""))
                self._pending = (address, password, user_input)
                if password is None and user_input.get(CONF_PAIR, False):
                    return await self.async_step_confirm_pairing()
                return await self._async_start_validation()
            # Never persist or echo a password through form defaults.
            self._defaults.update({k: v for k, v in user_input.items() if k != CONF_PASSWORD})

        if not self._defaults.get(CONF_MAC):
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
                if is_cube(info.manufacturer_data):
                    self._defaults = {CONF_MAC: info.address, CONF_BLE_NAME: info.name.rstrip("\x00")}
                    break
        return self.async_show_form(
            step_id="user",
            errors=errors,
            description_placeholders={
                "serial": self._probe.get("serial", "—"),
                "profile": self._probe.get("profile", "—"),
            },
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC, default=self._defaults.get(CONF_MAC, "")): str,
                    vol.Optional(CONF_BLE_NAME, default=self._defaults.get(CONF_BLE_NAME, "")): str,
                    vol.Optional(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_PROFILE, default=self._defaults.get(CONF_PROFILE, "auto")): vol.In(
                        ["auto", "gen2", "gen3", "gen2_zero"]
                    ),
                    vol.Optional(CONF_PAIR, default=self.source != "reconfigure"): bool,
                }
            ),
        )

    async def async_step_confirm_pairing(self, user_input=None):
        if user_input is not None:
            if not user_input.get("confirm", False):
                return self.async_show_form(
                    step_id="confirm_pairing",
                    data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
                    errors={"confirm": "confirmation_required"},
                )
            return await self._async_start_validation()
        return self.async_show_form(
            step_id="confirm_pairing",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
        )

    async def _async_start_validation(self):
        self._validated = None
        self._pairing_ready.clear()
        self._connect_task = self.hass.async_create_task(
            self._async_validate(*self._pending), "Segway Cube connection validation"
        )
        self._progress_task = self.hass.async_create_task(self._async_wait_for_pairing(), "Segway Cube pairing prompt")
        return await self.async_step_connect()

    async def _async_wait_for_pairing(self):
        ready = asyncio.create_task(self._pairing_ready.wait())
        try:
            await asyncio.wait((ready, self._connect_task), return_when=asyncio.FIRST_COMPLETED)
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)

    async def _async_validate(self, address, password, user_input):
        pair = password is None and user_input.get(CONF_PAIR, False)
        journal = get_journal(self.hass)
        record = None
        try:
            if pair:
                record = await journal.get(address)
                if record:
                    password = parse_password(record[CONF_PASSWORD])

            async def save_key(serial, key, confirmed):
                await journal.save(address, serial, key, confirmed)

            client = CubeClient(
                self.hass,
                address,
                user_input.get(CONF_BLE_NAME, ""),
                password,
                user_input.get(CONF_PROFILE, "auto"),
            )
            if self.source in ("reauth", "reconfigure"):
                entry = self._get_reauth_entry() if self.source == "reauth" else self._get_reconfigure_entry()
                client.source = entry.options.get(CONF_SOURCE, "auto")
            async with client.session(
                pair=pair,
                replace=pair,
                on_key=save_key if pair else None,
                on_pairing=self._pairing_ready.set if pair else None,
                recovery=record is not None,
                expected_serial=record.get("serial") if record else None,
            ) as session:
                await session.read(6, 0x30, 2)
            self._validated = {
                CONF_MAC: address,
                CONF_BLE_NAME: client.name,
                CONF_PASSWORD: client.password.hex(),
                CONF_PROFILE: client.profile,
                "serial": client.serial,
            }
        except PasswordRequired:
            self._errors = {"base": "password_required"}
        except PairingRequired:
            self._errors = {"base": "pairing_required"}
        except OSError:
            self._errors = {"base": "key_storage_failed"}
        except (BleakError, ProtocolError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Cube setup failed: %s", type(err).__name__)
            self._errors = {"base": "cannot_connect"}
        finally:
            if "client" in locals():
                self._probe = client.last_probe

    async def async_step_connect(self, user_input=None):
        task = self._progress_task or self._connect_task
        if not task.done():
            return self.async_show_progress(step_id="connect", progress_action="connecting", progress_task=task)
        await task
        if not self._connect_task.done():
            return self.async_show_progress_done(next_step_id="press_button")
        await self._connect_task
        return self.async_show_progress_done(next_step_id="connection_result")

    async def async_step_press_button(self, user_input=None):
        if not self._connect_task.done():
            return self.async_show_progress(
                step_id="press_button", progress_action="pairing", progress_task=self._connect_task
            )
        await self._connect_task
        return self.async_show_progress_done(next_step_id="connection_result")

    @callback
    def async_remove(self):
        for task in (self._connect_task, self._progress_task):
            if task is not None and not task.done():
                task.cancel()
        super().async_remove()

    async def async_step_connection_result(self, user_input=None):
        if self._validated is None:
            return await self.async_step_user()
        data = self._validated
        if self.source == "reauth":
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        if self.source == "reconfigure":
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=data)
        return self.async_create_entry(title="Segway Cube " + data[CONF_BLE_NAME], data=data)


class CubeOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SOURCE, default=opts.get(CONF_SOURCE, "auto")): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=source_options(self.hass, opts.get(CONF_SOURCE, "auto")),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional("scan_interval", default=opts.get("scan_interval", DEFAULT_INTERVAL)): vol.All(
                        vol.Coerce(int), vol.Range(min=15, max=3600)
                    ),
                    vol.Optional(
                        "detail_interval", default=opts.get("detail_interval", DEFAULT_DETAIL_INTERVAL)
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                    vol.Optional(CONF_ALLOW_CONTROL, default=opts.get(CONF_ALLOW_CONTROL, False)): bool,
                }
            ),
        )
