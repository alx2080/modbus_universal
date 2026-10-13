"""Modbus Universal: any Modbus device, with its registers defined in the UI."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError

from .connection import get_unit
from .const import (
    CONF_ADDRESS_BASE,
    CONF_MAX_GAP,
    CONF_PLATFORM,
    PLATFORM_BIT_GROUP,
    CONF_MESSAGE_SPACING,
    CONF_FAST_POLL,
    CONF_FAST_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_UNIT_ID,
    DEFAULT_ADDRESS_BASE,
    DEFAULT_MAX_GAP,
    DEFAULT_MESSAGE_SPACING,
    DEFAULT_FAST_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    SUBENTRY_REGISTER,
)
from .coordinator import (
    ModbusUniversalConfigEntry,
    ModbusUniversalCoordinator,
    ModbusUniversalRuntimeData,
)
from .device import ModbusUniversalDevice, bit_group_members
from .helpers import build_params
from .registry import async_prepare_registries

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ModbusUniversalConfigEntry
) -> bool:
    """Set up one Modbus device from a config entry."""
    options = entry.options
    params = build_params(entry.data)
    try:
        unit = get_unit(hass, entry, params, int(entry.data[CONF_UNIT_ID]))
    except HomeAssistantError as err:
        # Another integration already talks to this port with other settings
        # (for example a different baud rate). Only the user can fix that.
        raise ConfigEntryError(str(err)) from err

    unit.require_timeout(float(options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)))
    unit.set_message_spacing(
        float(options.get(CONF_MESSAGE_SPACING, DEFAULT_MESSAGE_SPACING))
    )

    address_base = int(options.get(CONF_ADDRESS_BASE, DEFAULT_ADDRESS_BASE))
    max_gap = int(options.get(CONF_MAX_GAP, DEFAULT_MAX_GAP))
    normal_points: dict[str, dict] = {}
    fast_points: dict[str, dict] = {}
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_REGISTER:
            continue
        target = fast_points if subentry.data.get(CONF_FAST_POLL) else normal_points
        target[subentry_id] = dict(subentry.data)

    # Both devices read through the same unit, so the shared connection
    # serializes their requests: fast reads slot in between normal ones.
    normal_device = ModbusUniversalDevice(
        unit, normal_points, address_base=address_base, max_gap=max_gap
    )
    fast_device = ModbusUniversalDevice(
        unit, fast_points, address_base=address_base, max_gap=max_gap
    )
    for key, reason in (normal_device.invalid | fast_device.invalid).items():
        _LOGGER.error(
            "%s: register %r is misconfigured and skipped: %s",
            entry.title,
            entry.subentries[key].title,
            reason,
        )

    normal = ModbusUniversalCoordinator(
        hass,
        entry,
        normal_device,
        timedelta(seconds=float(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))),
    )
    fast: ModbusUniversalCoordinator | None = None
    if fast_points:
        fast = ModbusUniversalCoordinator(
            hass,
            entry,
            fast_device,
            timedelta(
                seconds=float(
                    options.get(CONF_FAST_SCAN_INTERVAL, DEFAULT_FAST_SCAN_INTERVAL)
                )
            ),
            fast=True,
        )
        # The fast poll notices a wedged link first; let only it recycle it.
        normal.recycle_on_timeout = False

    # The device shows up even before any register is added to it. Entities of
    # registers that were deleted are removed here.
    async_prepare_registries(
        hass,
        entry,
        normal.device_info,
        _unique_ids(entry),
    )
    await normal.async_config_entry_first_refresh()
    if fast is not None:
        await fast.async_config_entry_first_refresh()
    entry.runtime_data = ModbusUniversalRuntimeData(normal=normal, fast=fast)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Adding, editing or deleting a register (a subentry) or changing options
    # rebuilds the read plan.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _unique_ids(entry: ModbusUniversalConfigEntry) -> list[str]:
    """Unique ids of every entity this entry should have (others are removed)."""
    ids = [f"{entry.entry_id}_link"]
    for key, subentry in entry.subentries.items():
        if subentry.data.get(CONF_PLATFORM) != PLATFORM_BIT_GROUP:
            ids.append(f"{entry.entry_id}_{key}")
            continue
        try:
            members = bit_group_members(subentry.data)
        except ValueError:
            continue
        ids.extend(f"{entry.entry_id}_{key}_bit{bit}" for bit, _ in members)
    return ids


async def _async_update_listener(
    hass: HomeAssistant, entry: ModbusUniversalConfigEntry
) -> None:
    """Reload after the configuration changed."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: ModbusUniversalConfigEntry
) -> bool:
    """Unload a config entry; the shared connection is released automatically."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
