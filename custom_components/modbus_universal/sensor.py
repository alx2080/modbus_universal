"""Sensors defined in the UI."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DATA_TYPE, CONF_PRECISION, DT_STRING
from .coordinator import ModbusUniversalConfigEntry, ModbusUniversalCoordinator
from .entity import ModbusUniversalEntity, async_setup_platform_entities

CONF_DEVICE_CLASS = "device_class"
CONF_STATE_CLASS = "state_class"
CONF_UNIT_OF_MEASUREMENT = "unit_of_measurement"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ModbusUniversalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    async_setup_platform_entities(
        hass, entry, async_add_entities, "sensor", ModbusUniversalSensor
    )


class ModbusUniversalSensor(ModbusUniversalEntity, SensorEntity):
    """A register shown as a sensor."""

    def __init__(
        self, coordinator: ModbusUniversalCoordinator, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator, subentry)
        point = self.point
        if point.get(CONF_DATA_TYPE) != DT_STRING:
            if device_class := point.get(CONF_DEVICE_CLASS):
                self._attr_device_class = SensorDeviceClass(device_class)
            if state_class := point.get(CONF_STATE_CLASS):
                self._attr_state_class = SensorStateClass(state_class)
            self._attr_native_unit_of_measurement = (
                point.get(CONF_UNIT_OF_MEASUREMENT) or None
            )
            if (precision := point.get(CONF_PRECISION)) is not None:
                self._attr_suggested_display_precision = int(precision)

    @property
    def native_value(self) -> Any:
        return self.raw_value
