"""Switches defined in the UI."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_BIT, CONF_INVERT, CONF_OFF_VALUE, CONF_ON_VALUE, CONF_REGISTER_TYPE, REG_COIL
from .coordinator import ModbusUniversalConfigEntry, ModbusUniversalCoordinator
from .entity import ModbusUniversalEntity, async_setup_platform_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ModbusUniversalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    async_setup_platform_entities(
        hass, entry, async_add_entities, "switch", ModbusUniversalSwitch
    )


class ModbusUniversalSwitch(ModbusUniversalEntity, SwitchEntity):
    """A coil, a register bit, or a register with on/off values."""

    def __init__(
        self, coordinator: ModbusUniversalCoordinator, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator, subentry)
        point = self.point
        # Coils and single bits are booleans; a whole register uses values.
        self._boolean = (
            point.get(CONF_REGISTER_TYPE) == REG_COIL or point.get(CONF_BIT) is not None
        )
        self._invert = bool(point.get(CONF_INVERT))
        self._on_value = int(point.get(CONF_ON_VALUE, 1))
        self._off_value = int(point.get(CONF_OFF_VALUE, 0))

    @property
    def is_on(self) -> bool | None:
        value = self.raw_value
        if value is None:
            return None
        state = bool(value) if self._boolean else value == self._on_value
        return state != self._invert

    def _value_for(self, on: bool) -> Any:
        on = on != self._invert
        if self._boolean:
            return on
        return self._on_value if on else self._off_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_write(self._value_for(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_write(self._value_for(False))
