"""Binary sensors defined in the UI."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from datetime import timedelta
import time
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_INVERT,
    CONF_LINK_TIMEOUT,
    CONF_PLATFORM,
    DEFAULT_LINK_TIMEOUT,
    PLATFORM_BIT_GROUP,
    SUBENTRY_REGISTER,
)
from .coordinator import (
    ModbusUniversalConfigEntry,
    ModbusUniversalCoordinator,
    ModbusUniversalRuntimeData,
)
from .device import bit_group_members, split_bit_label
from .entity import ModbusUniversalEntity, async_setup_platform_entities

CONF_DEVICE_CLASS = "device_class"
BINARY_DEVICE_CLASSES = frozenset(c.value for c in BinarySensorDeviceClass)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ModbusUniversalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    # The connection status belongs to the device, not to a register.
    async_add_entities([ModbusUniversalLinkSensor(entry)])
    async_setup_platform_entities(
        hass, entry, async_add_entities, "binary_sensor", ModbusUniversalBinarySensor
    )
    # A bit group is one register read, shown as one binary sensor per bit.
    runtime = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if (
            subentry.subentry_type != SUBENTRY_REGISTER
            or subentry.data.get(CONF_PLATFORM) != PLATFORM_BIT_GROUP
        ):
            continue
        try:
            members = bit_group_members(subentry.data)
        except ValueError:
            continue  # reported at setup as a misconfigured register
        coordinator = runtime.coordinator_for(subentry_id)
        async_add_entities(
            ModbusUniversalBitSensor(coordinator, subentry, bit, name)
            for bit, name in members
        )


class ModbusUniversalBinarySensor(ModbusUniversalEntity, BinarySensorEntity):
    """A coil, discrete input or register bit shown as a binary sensor."""

    def __init__(
        self, coordinator: ModbusUniversalCoordinator, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator, subentry)
        if device_class := self.point.get(CONF_DEVICE_CLASS):
            self._attr_device_class = BinarySensorDeviceClass(device_class)
        self._invert = bool(self.point.get(CONF_INVERT))

    @property
    def is_on(self) -> bool | None:
        value = self.raw_value
        if value is None:
            return None
        return bool(value) != self._invert


class ModbusUniversalBitSensor(ModbusUniversalBinarySensor):
    """One bit of a bit group register."""

    def __init__(
        self,
        coordinator: ModbusUniversalCoordinator,
        subentry: ConfigSubentry,
        bit: int,
        name: str | None,
    ) -> None:
        super().__init__(coordinator, subentry)
        self._bit = bit
        name, device_class, invert = split_bit_label(name)
        self._attr_name = name or f"{subentry.title} {bit}"
        if device_class in BINARY_DEVICE_CLASSES:
            # A class given for this bit overrides the class of the group.
            self._attr_device_class = BinarySensorDeviceClass(device_class)
        # "inv" on a bit flips it relative to the group setting.
        self._invert = self._invert != invert
        self._attr_unique_id = bit_unique_id(
            coordinator.config_entry.entry_id, subentry.subentry_id, bit
        )
        self._attr_extra_state_attributes = {"bit": bit}

    @property
    def is_on(self) -> bool | None:
        value = self.raw_value
        if value is None:
            return None
        return bool((int(value) >> self._bit) & 1) != self._invert


def bit_unique_id(entry_id: str, subentry_id: str, bit: int) -> str:
    """Unique id of one bit sensor of a bit group."""
    return f"{entry_id}_{subentry_id}_bit{bit}"


class ModbusUniversalLinkSensor(BinarySensorEntity):
    """Connection status: off when nothing was read for longer than the timeout."""

    _attr_has_entity_name = True
    _attr_translation_key = "link"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ModbusUniversalConfigEntry) -> None:
        self._runtime: ModbusUniversalRuntimeData = entry.runtime_data
        self._timeout = float(entry.options.get(CONF_LINK_TIMEOUT, DEFAULT_LINK_TIMEOUT))
        self._attr_unique_id = f"{entry.entry_id}_link"
        self._attr_device_info = self._runtime.normal.device_info

    @property
    def available(self) -> bool:
        # The status itself must stay usable while the device is unreachable.
        return True

    def _compute(self) -> bool | None:
        if not self._runtime.polls_anything:
            return None  # nothing is read, so the link cannot be judged
        last = self._runtime.last_success
        return last is not None and time.monotonic() - last <= self._timeout

    @property
    def is_on(self) -> bool | None:
        return self._compute()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._runtime.last_success_utc
        return {
            "last_seen": last.isoformat() if last else None,
            "timeout": self._timeout,
        }

    async def async_added_to_hass(self) -> None:
        last_state: list[bool | None] = [self._compute()]

        @callback
        def _recheck(*_: Any) -> None:
            # A poll finished: refresh the flag and the last_seen attribute.
            last_state[0] = self._compute()
            self.async_write_ha_state()

        for coordinator in self._runtime.coordinators:
            self.async_on_remove(coordinator.async_add_listener(_recheck))
        # Polls that keep failing do not notify listeners again, so the
        # timeout is checked on a clock of its own.
        interval = min(1.0, max(self._timeout / 4, 0.1))

        @callback
        def _tick(_now: Any) -> None:
            state = self._compute()
            if state != last_state[0]:
                last_state[0] = state
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, _tick, timedelta(seconds=interval))
        )
