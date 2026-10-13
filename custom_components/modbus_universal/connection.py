"""Get Modbus units from Home Assistant's shared connections.

Home Assistant's ``modbus`` integration hands out units over connections it
shares between integrations (``async_get_unit`` / ``async_get_temporary_unit``).
On older Home Assistant releases that predate that API, a private connection is
opened instead, so the integration still works.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from modbus_connection import ModbusUnit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .helpers import ModbusParams

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.components.modbus import (
        async_get_temporary_unit as _ha_temporary_unit,
        async_get_unit as _ha_get_unit,
    )
except ImportError:  # Home Assistant without the shared-connection API
    _ha_get_unit = None
    _ha_temporary_unit = None


def get_unit(
    hass: HomeAssistant, entry: ConfigEntry, params: ModbusParams, unit_id: int
) -> ModbusUnit:
    """Return a unit for this entry; released automatically on unload.

    Raises ``HomeAssistantError`` if the device is already used by another
    entry over different link settings.
    """
    if _ha_get_unit is not None:
        return _ha_get_unit(hass, entry, params, unit_id)

    from modbus_connection.tmodbus import ModbusConnection  # noqa: PLC0415

    _LOGGER.warning(
        "This Home Assistant version has no shared Modbus connections; "
        "%s opens its own connection",
        entry.title,
    )
    connection = ModbusConnection(params)
    entry.async_on_unload(connection.close)
    return connection.for_unit(unit_id)


@asynccontextmanager
async def temporary_unit(
    hass: HomeAssistant, params: ModbusParams, unit_id: int
) -> AsyncIterator[ModbusUnit]:
    """Hold a unit for the duration of the context (config flow probing)."""
    if _ha_temporary_unit is not None:
        async with _ha_temporary_unit(hass, params, unit_id) as unit:
            yield unit
        return

    from modbus_connection.tmodbus import ModbusConnection  # noqa: PLC0415

    connection = ModbusConnection(params)
    try:
        yield connection.for_unit(unit_id)
    finally:
        await connection.close()
