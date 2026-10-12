"""Private, serialized recovery journal for interrupted button pairing."""

import asyncio
import json
from pathlib import Path

from homeassistant.helpers.storage import Store

from .const import DOMAIN


class PairingJournal:
    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, DOMAIN + ".pairing", private=True, atomic_writes=True)
        self.lock = asyncio.Lock()

    async def get(self, address):
        async with self.lock:
            records = await self.store.async_load() or {}
            return records.get(address)

    async def save(self, address, serial, key, confirmed):
        async with self.lock:
            records = dict(await self.store.async_load() or {})
            records[address] = {"serial": serial, "password": key.hex(), "confirmed": confirmed}
            await self.store.async_save(records)
            # Store logs WriteError instead of raising it. Verify the on-disk
            # record rather than its cache before changing a station credential.
            await self.hass.async_add_executor_job(
                _verify_saved, self.store.path, address, records[address]
            )


def get_journal(hass):
    key = DOMAIN + ".pairing_journal"
    if key not in hass.data:
        hass.data[key] = PairingJournal(hass)
    return hass.data[key]


def _verify_saved(path, address, record):
    try:
        saved = json.loads(Path(path).read_text())["data"].get(address)
    except (ValueError, KeyError) as err:
        raise OSError("Pairing recovery journal is unreadable") from err
    if saved != record:
        raise OSError("Bluetooth key was not durably saved")
