"""Diagnostics omit credentials, identifiers and authentication material."""

from .registers import REGISTERS


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    redacted_keys = {r.key for r in REGISTERS if r.key.endswith(("Pn", "Sn")) or r.key in ("rSN", "rCPUId")}
    return {
        "options": dict(entry.options),
        "profile": coordinator.client.profile,
        "rssi": coordinator.client.rssi(),
        "bluetooth_source": coordinator.client.source,
        "last_connection_source": coordinator.client.last_connection_source,
        "poll_count": coordinator.poll_count,
        "battery_count": coordinator.battery_count,
        "raw": {k: v for k, v in coordinator.raw.items() if k not in redacted_keys},
        "failures": dict(coordinator.failures),
    }
