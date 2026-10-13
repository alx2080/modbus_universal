"""Selects (register value <-> named option) defined in the UI."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_OPTIONS
from .coordinator import ModbusUniversalConfigEntry, ModbusUniversalCoordinator
from .entity import ModbusUniversalEntity, async_setup_platform_entities
from .helpers import parse_options


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ModbusUniversalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects."""
    async_setup_platform_entities(
        hass, entry, async_add_entities, "select", ModbusUniversalSelect
    )


class ModbusUniversalSelect(ModbusUniversalEntity, SelectEntity):
    """A holding register whose values map to named modes."""

    def __init__(
        self, coordinator: ModbusUniversalCoordinator, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator, subentry)
        self._by_value = parse_options(self.point.get(CONF_OPTIONS, ""))
        self._by_label = {label: value for value, label in self._by_value.items()}
        self._attr_options = list(self._by_value.values())

    @property
    def current_option(self) -> str | None:
        value = self.raw_value
        return None if value is None else self._by_value.get(int(value))

    async def async_select_option(self, option: str) -> None:
        await self.async_write(self._by_label[option])
