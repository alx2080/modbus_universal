"""Writable numbers defined in the UI."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_MAX, CONF_MIN, CONF_STEP
from .coordinator import ModbusUniversalConfigEntry, ModbusUniversalCoordinator
from .entity import ModbusUniversalEntity, async_setup_platform_entities

CONF_DEVICE_CLASS = "device_class"
CONF_MODE = "mode"
CONF_UNIT_OF_MEASUREMENT = "unit_of_measurement"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ModbusUniversalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up numbers."""
    async_setup_platform_entities(
        hass, entry, async_add_entities, "number", ModbusUniversalNumber
    )


class ModbusUniversalNumber(ModbusUniversalEntity, NumberEntity):
    """A holding register written as a number (setpoint, limit, ...)."""

    def __init__(
        self, coordinator: ModbusUniversalCoordinator, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator, subentry)
        point = self.point
        self._attr_native_min_value = float(point.get(CONF_MIN, 0))
        self._attr_native_max_value = float(point.get(CONF_MAX, 65535))
        self._attr_native_step = float(point.get(CONF_STEP, 1))
        self._attr_mode = NumberMode(point.get(CONF_MODE, NumberMode.BOX))
        self._attr_native_unit_of_measurement = (
            point.get(CONF_UNIT_OF_MEASUREMENT) or None
        )
        if device_class := point.get(CONF_DEVICE_CLASS):
            self._attr_device_class = NumberDeviceClass(device_class)

    @property
    def native_value(self) -> float | None:
        return self.raw_value

    async def async_set_native_value(self, value: float) -> None:
        await self.async_write(value)
