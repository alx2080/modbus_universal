"""Base entity for Modbus Universal."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from modbus_connection import ModbusError

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PLATFORM, DOMAIN, SUBENTRY_REGISTER
from .coordinator import ModbusUniversalConfigEntry, ModbusUniversalCoordinator


class ModbusUniversalEntity(CoordinatorEntity[ModbusUniversalCoordinator]):
    """An entity backed by one UI-defined register."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ModbusUniversalCoordinator, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator)
        self.key = subentry.subentry_id
        self.point: dict[str, Any] = dict(subentry.data)
        self._attr_name = subentry.title
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.key in self.coordinator.device.keys
            and self.key not in self.coordinator.failed
        )

    @property
    def raw_value(self) -> Any:
        """The decoded value from the last poll."""
        return (self.coordinator.data or {}).get(self.key)

    async def async_write(self, value: Any) -> None:
        """Write to the register, translating failures for the UI."""
        try:
            await self.coordinator.async_write(self.key, value)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"name": self.name or self.key, "error": str(err)},
            ) from err
        except (ValueError, OverflowError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_invalid",
                translation_placeholders={"name": self.name or self.key, "error": str(err)},
            ) from err


def async_setup_platform_entities(
    hass: HomeAssistant,
    entry: ModbusUniversalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform: str,
    factory: Callable[[ModbusUniversalCoordinator, ConfigSubentry], ModbusUniversalEntity],
) -> None:
    """Add one entity per register subentry of this platform.

    The entities belong to the device in the main entry, not to their
    subentries: a device can only belong to one subentry, so tying entities of
    several registers to their subentries would pull the shared device back and
    forth. Entities of deleted registers are removed at setup (see registry.py).
    """
    runtime = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if (
            subentry.subentry_type != SUBENTRY_REGISTER
            or subentry.data.get(CONF_PLATFORM) != platform
        ):
            continue
        async_add_entities([factory(runtime.coordinator_for(subentry_id), subentry)])
