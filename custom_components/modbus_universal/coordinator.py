"""Polling coordinator for Modbus Universal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

from modbus_connection import ModbusError, ModbusTimeoutError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .device import ModbusUniversalDevice
from .helpers import describe

_LOGGER = logging.getLogger(__name__)

_TIMEOUTS_BEFORE_RECYCLE = 3

FAILED_KEY = "_failed"  # never a subentry id

type ModbusUniversalConfigEntry = ConfigEntry[ModbusUniversalRuntimeData]


@dataclass
class _State:
    failed: frozenset[str] = frozenset()
    timeouts: int = 0


class ModbusUniversalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll every configured register of one Modbus unit."""

    config_entry: ModbusUniversalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ModbusUniversalConfigEntry,
        device: ModbusUniversalDevice,
        interval: timedelta,
        *,
        fast: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} (fast)" if fast else entry.title,
            update_interval=interval,
            # With fast polling most reads return the same values; only notify
            # entities when something actually changed.
            always_update=False,
        )
        self.device = device
        self.fast = fast
        # Only one coordinator per link may recycle it on repeated timeouts,
        # or one could drop the link under the other's poll in flight.
        self.recycle_on_timeout = True
        self._state = _State()
        # When the device last answered (monotonic, and wall clock for display).
        self.last_success: float | None = None
        self.last_success_utc = None
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Modbus",
            model=describe(entry.data),
        )

    @property
    def failed(self) -> frozenset[str]:
        """Keys of the points the last poll could not read."""
        return self._state.failed

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            result = await self.device.async_update()
        except ModbusTimeoutError as err:
            self._state.timeouts += 1
            if (
                self.recycle_on_timeout
                and self._state.timeouts >= _TIMEOUTS_BEFORE_RECYCLE
            ):
                # A link that is up but silent (typical for some RS485 bridges):
                # drop it, the next request opens a fresh one.
                self._state.timeouts = 0
                await self.device.unit.disconnect()
            raise UpdateFailed(f"Timeout: {err}") from err
        except ModbusError as err:
            raise UpdateFailed(str(err)) from err
        self._state.timeouts = 0

        if result.failed and not result.values:
            first = next(iter(result.failed.values()))
            raise UpdateFailed(f"No register could be read: {first}")
        for key in sorted(result.failed.keys() - self._state.failed):
            _LOGGER.warning(
                "%s: register %s could not be read: %s",
                self.config_entry.title,
                self._title(key),
                result.failed[key],
            )
        self._state.failed = frozenset(result.failed)
        if self.device.keys:
            # Any answered read proves the link, even if some registers failed.
            self.last_success = time.monotonic()
            self.last_success_utc = dt_util.utcnow()
        # The failed set is part of the data, so a register that recovers with
        # an unchanged value still notifies its entity (always_update=False).
        return {**result.values, FAILED_KEY: self._state.failed}

    def _title(self, key: str) -> str:
        subentry = self.config_entry.subentries.get(key)
        return subentry.title if subentry else key

    async def async_write(self, key: str, value: Any) -> None:
        """Write a value, then refresh so entities show what the device took."""
        await self.device.async_write(key, value)
        await self.async_request_refresh()


@dataclass
class ModbusUniversalRuntimeData:
    """The coordinators of one device: normal registers and fast-polled ones."""

    normal: ModbusUniversalCoordinator
    fast: ModbusUniversalCoordinator | None

    @property
    def coordinators(self) -> list[ModbusUniversalCoordinator]:
        """Every active coordinator."""
        return [c for c in (self.fast, self.normal) if c is not None]

    @property
    def unit(self):
        """The Modbus unit both coordinators read through."""
        return self.normal.device.unit

    def coordinator_for(self, key: str) -> ModbusUniversalCoordinator:
        """The coordinator that polls this register."""
        if self.fast is not None and key in self.fast.device.keys:
            return self.fast
        return self.normal

    @property
    def polls_anything(self) -> bool:
        """Whether any register is polled, so the link state can be judged."""
        return any(c.device.keys for c in self.coordinators)

    @property
    def last_success(self) -> float | None:
        """Monotonic time of the latest successful read on any poll."""
        times = [c.last_success for c in self.coordinators if c.last_success]
        return max(times) if times else None

    @property
    def last_success_utc(self):
        """Wall-clock time of the latest successful read on any poll."""
        times = [c.last_success_utc for c in self.coordinators if c.last_success_utc]
        return max(times) if times else None
