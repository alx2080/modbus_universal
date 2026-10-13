"""Diagnostics: the register map and the raw values the device returns."""

from __future__ import annotations

from typing import Any

from modbus_connection import ModbusError

from homeassistant.core import HomeAssistant

from .coordinator import FAILED_KEY, ModbusUniversalConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ModbusUniversalConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    raw: dict[str, Any] = {}
    for coordinator in runtime.coordinators:
        label = "fast" if coordinator.fast else "normal"
        try:
            raw[label] = await coordinator.device.async_read_raw()
        except ModbusError as err:
            raw[label] = f"read failed: {err}"
    values = {
        k: v
        for coordinator in runtime.coordinators
        for k, v in (coordinator.data or {}).items()
        if k != FAILED_KEY
    }
    return {
        "connection": dict(entry.data),
        "options": dict(entry.options),
        "registers": {
            subentry.title: dict(subentry.data) for subentry in entry.subentries.values()
        },
        "invalid": {
            k: v for c in runtime.coordinators for k, v in c.device.invalid.items()
        },
        "failed": sorted(k for c in runtime.coordinators for k in c.failed),
        "values": {
            (entry.subentries[k].title if k in entry.subentries else k): v
            for k, v in values.items()
        },
        "raw": raw,
    }
