import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ConfigEntryNotReady


async def test_stalled_first_connection_becomes_retryable_setup(monkeypatch):
    path = Path(__file__).parents[1] / "custom_components/segway_cube/__init__.py"
    spec = importlib.util.spec_from_file_location("cube_test.setup", path, submodule_search_locations=None)
    integration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integration)

    class StalledCoordinator:
        def __init__(self, *args):
            pass

        async def async_config_entry_first_refresh(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(integration, "CubeCoordinator", StalledCoordinator)
    monkeypatch.setattr(integration, "STARTUP_TIMEOUT", 0)
    entry = SimpleNamespace(data={"mac": "AA:BB:CC:DD:EE:FF", "password": "ab" * 16}, options={})
    with pytest.raises(ConfigEntryNotReady, match="retry in the background"):
        await integration.async_setup_entry(None, entry)
