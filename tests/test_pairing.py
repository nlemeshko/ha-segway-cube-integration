import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cube_test import pairing


async def test_private_journal_preserves_two_concurrent_station_keys(monkeypatch, tmp_path):
    records = None

    async def save(data):
        nonlocal records
        await asyncio.sleep(0)
        records = data
        (tmp_path / "journal").write_text(json.dumps({"data": data}))

    store = SimpleNamespace(path=str(tmp_path / "journal"), async_load=AsyncMock(side_effect=lambda: records), async_save=save)
    factory = AsyncMock()
    # The constructor is synchronous, so capture its options separately.
    def make_store(*args, **kwargs):
        assert kwargs == {"private": True, "atomic_writes": True}
        factory(*args, **kwargs).close()
        return store

    monkeypatch.setattr(pairing, "Store", make_store)
    async def executor(func, *args):
        return func(*args)

    hass = SimpleNamespace(data={}, async_add_executor_job=executor)
    journal = pairing.get_journal(hass)
    assert pairing.get_journal(hass) is journal
    await asyncio.gather(journal.save("A", "SERIAL-A", bytes(16), False),
                         journal.save("B", "SERIAL-B", bytes([1]) * 16, True))
    assert records["A"]["confirmed"] is False
    assert records["B"]["confirmed"] is True
    assert (await journal.get("A"))["serial"] == "SERIAL-A"


async def test_silent_storage_failure_stops_pairing(monkeypatch, tmp_path):
    import pytest

    store = SimpleNamespace(path=str(tmp_path / "missing"), async_load=AsyncMock(return_value=None),
                            async_save=AsyncMock())
    monkeypatch.setattr(pairing, "Store", lambda *args, **kwargs: store)
    async def executor(func, *args):
        return func(*args)

    journal = pairing.PairingJournal(SimpleNamespace(async_add_executor_job=executor))
    with pytest.raises(OSError):
        await journal.save("A", "SERIAL", bytes(16), False)
