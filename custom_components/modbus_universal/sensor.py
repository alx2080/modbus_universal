"""Sensors defined in the UI."""

from __future__ import annotations

from typing import Any

import logging

from homeassistant.components.sensor import (
    DEVICE_CLASS_STATE_CLASSES,
    DEVICE_CLASS_UNITS,
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

_LOGGER = logging.getLogger(__name__)

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
            unit = point.get(CONF_UNIT_OF_MEASUREMENT) or None
            device_class = (
                SensorDeviceClass(point[CONF_DEVICE_CLASS])
                if point.get(CONF_DEVICE_CLASS)
                else None
            )
            state_class = (
                SensorStateClass(point[CONF_STATE_CLASS])
                if point.get(CONF_STATE_CLASS)
                else None
            )
            if device_class is not None and (
                (allowed := DEVICE_CLASS_UNITS.get(device_class)) is not None
                and unit not in allowed
            ):
                # Saved before the form checked this (e.g. "power" in kWh):
                # keep the value and unit, drop the class that contradicts it.
                _LOGGER.warning(
                    "%s: unit %s does not fit device class %s; the class is ignored. "
                    "Edit the register to pick a matching class or unit",
                    subentry.title, unit, device_class.value,
                )
                device_class = None
            if (
                device_class is not None
                and state_class is not None
                and (classes := DEVICE_CLASS_STATE_CLASSES.get(device_class)) is not None
                and state_class not in classes
            ):
                _LOGGER.warning(
                    "%s: state class %s does not fit device class %s; the state class "
                    "is ignored. Edit the register to fix it",
                    subentry.title, state_class.value, device_class.value,
                )
                state_class = None
            self._attr_device_class = device_class
            self._attr_state_class = state_class
            self._attr_native_unit_of_measurement = unit
            if (precision := point.get(CONF_PRECISION)) is not None:
                self._attr_suggested_display_precision = int(precision)

    @property
    def native_value(self) -> Any:
        return self.raw_value
