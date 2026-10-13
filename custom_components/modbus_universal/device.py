"""Device layer: turns UI-defined register descriptions into Modbus reads/writes.

This module has no Home Assistant imports, so the register handling can be
tested against the modbus-connection mock without Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import re
from typing import Any

from modbus_connection import ModbusExceptionError, ModbusUnit
from modbus_connection.model import (
    CoilField,
    DiscreteInputField,
    FloatField,
    ManualComponent,
    NumberField,
    PackedBitField,
    StringField,
)

from .const import (
    CONF_ADDRESS,
    CONF_BIT,
    CONF_BYTE_SWAP,
    CONF_DATA_TYPE,
    CONF_FORCE_FC16,
    CONF_LENGTH,
    CONF_OFFSET,
    CONF_PLATFORM,
    CONF_REGISTER_TYPE,
    CONF_SCALE,
    CONF_WORD_ORDER,
    DT_FLOAT32,
    DT_FLOAT64,
    DT_INT16,
    DT_INT32,
    DT_INT64,
    DT_STRING,
    DT_UINT16,
    DT_UINT32,
    DT_UINT64,
    REG_COIL,
    REG_DISCRETE,
    REG_HOLDING,
    REG_INPUT,
    BIT_GROUP_WIDTH,
    CONF_BIT_NAMES,
    CONF_BITS,
    PLATFORM_BIT_GROUP,
)

_LOGGER = logging.getLogger(__name__)

# data type -> (register count, signed)
_INT_TYPES: dict[str, tuple[int, bool]] = {
    DT_INT16: (1, True),
    DT_UINT16: (1, False),
    DT_INT32: (2, True),
    DT_UINT32: (2, False),
    DT_INT64: (4, True),
    DT_UINT64: (4, False),
}
_FLOAT_TYPES: dict[str, int] = {DT_FLOAT32: 2, DT_FLOAT64: 4}

WRITABLE_PLATFORMS = frozenset({"switch", "number", "select"})


def _swap_bytes(words: list[int]) -> list[int]:
    """Swap the two bytes inside every 16-bit word (Modbus 'swap: byte')."""
    return [((w & 0xFF) << 8) | ((w >> 8) & 0xFF) for w in words]


class _ByteSwappedNumberField(NumberField[Any]):
    """Integer field for devices that send each register little-endian."""

    def decode(self, words: list[int], scale_exponent: int | None = None) -> Any:
        return super().decode(_swap_bytes(words), scale_exponent)

    def encode(self, value: Any, scale_exponent: int | None = None) -> list[int]:
        return _swap_bytes(super().encode(value, scale_exponent))


class _ByteSwappedFloatField(FloatField):
    """Float field for devices that send each register little-endian."""

    def decode(self, words: list[int], scale_exponent: int | None = None) -> Any:
        return super().decode(_swap_bytes(words), scale_exponent)

    def encode(self, value: Any, scale_exponent: int | None = None) -> list[int]:
        return _swap_bytes(super().encode(value, scale_exponent))


class _ByteSwappedStringField(StringField):
    """String field with the characters of each register swapped."""

    def decode(self, words: list[int], scale_exponent: int | None = None) -> str:
        return super().decode(_swap_bytes(words), scale_exponent)

    def encode(self, value: Any, scale_exponent: int | None = None) -> list[int]:
        return _swap_bytes(super().encode(value, scale_exponent))


_NAMED_LINE = re.compile(r"^\s*(\d+)\s*[=:]\s*(.*?)\s*$")


def bit_group_width(point: Mapping[str, Any]) -> int:
    """How many bits the register of a bit group has (16, 32 or 64)."""
    return BIT_GROUP_WIDTH.get(point.get(CONF_DATA_TYPE, DT_UINT16), 16)


def parse_bits(text: str | None, width: int) -> list[int]:
    """Parse '0-7, 12, 15' into a sorted list of bit numbers; empty = all bits.

    Raises ``ValueError`` for bad syntax or a bit outside the register.
    """
    text = (text or "").strip()
    if not text:
        return list(range(width))
    bits: set[int] = set()
    for part in re.split(r"[,;\s]+", text):
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        start = int(lo)
        end = int(hi) if sep else start
        if start > end:
            start, end = end, start
        if start < 0 or end >= width:
            raise ValueError(f"bit {end if end >= width else start} is outside 0-{width - 1}")
        bits.update(range(start, end + 1))
    return sorted(bits)


def parse_bit_names(text: str | None, bits: list[int]) -> dict[int, str]:
    """Names for the bits of a group.

    Each line is either 'N=Name' (or 'N: Name') for bit N, or just a name,
    which goes to the next selected bit after the previous line's bit. Empty
    lines skip a bit, so a plain list can follow the register map line by line.

    Raises ``ValueError`` for a name of a bit that is not in the group.
    """
    names: dict[int, str] = {}
    if not (text or "").strip():
        return names
    position = 0  # index into bits for the next unnumbered line
    for line in (text or "").splitlines():
        if match := _NAMED_LINE.match(line):
            bit = int(match.group(1))
            if bit not in bits:
                raise ValueError(f"bit {bit} is not in the group")
            if match.group(2):
                names[bit] = match.group(2)
            position = bits.index(bit) + 1
            continue
        if position >= len(bits):
            if line.strip():
                raise ValueError("more names than bits")
            continue
        if line.strip():
            names[bits[position]] = line.strip()
        position += 1
    return names


_INVERT_WORDS = frozenset({"!", "inv", "invert", "інв", "инв"})


def split_bit_label(label: str | None) -> tuple[str | None, str | None, bool]:
    """Split 'Name | device_class | inv' into (name, device class, invert).

    Every part after the name is optional and may come in any order.
    """
    if not label:
        return None, None, False
    name, *extras = (part.strip() for part in label.split("|"))
    device_class: str | None = None
    invert = False
    for extra in extras:
        if extra.lower() in _INVERT_WORDS:
            invert = True
        elif extra:
            device_class = extra.lower()
    return name or None, device_class, invert


def bit_group_members(point: Mapping[str, Any]) -> list[tuple[int, str | None]]:
    """(bit, name or None) for every binary sensor of a bit group.

    Raises ``ValueError`` for an invalid bit list or names.
    """
    bits = parse_bits(point.get(CONF_BITS), bit_group_width(point))
    names = parse_bit_names(point.get(CONF_BIT_NAMES), bits)
    return [(bit, names.get(bit)) for bit in bits]


def build_target(
    point: Mapping[str, Any], address_base: int = 0
) -> tuple[Any, str | None]:
    """Build the modbus-connection field for one UI-defined point.

    Returns the field and the register space to pass to ``ManualComponent.add``
    (``None`` for coils and discrete inputs, whose space is fixed).

    Raises ``ValueError`` for an inconsistent description.
    """
    platform = point[CONF_PLATFORM]
    register_type = point.get(CONF_REGISTER_TYPE, REG_HOLDING)
    address = int(point[CONF_ADDRESS]) - address_base
    if address < 0:
        raise ValueError(f"address {point[CONF_ADDRESS]} is below the address base")
    writable = platform in WRITABLE_PLATFORMS
    force_fc16 = bool(point.get(CONF_FORCE_FC16)) and writable

    if register_type == REG_COIL:
        return CoilField(address, writable=writable), None
    if register_type == REG_DISCRETE:
        if writable:
            raise ValueError("discrete inputs are read-only")
        return DiscreteInputField(address), None
    if register_type not in (REG_HOLDING, REG_INPUT):
        raise ValueError(f"unknown register type {register_type!r}")
    if writable and register_type == REG_INPUT:
        raise ValueError("input registers are read-only")

    if platform == PLATFORM_BIT_GROUP:
        # The whole register as an unsigned integer; entities pick their bit.
        data_type = point.get(CONF_DATA_TYPE, DT_UINT16)
        if data_type not in BIT_GROUP_WIDTH:
            raise ValueError(f"a bit group needs uint16/32/64, not {data_type!r}")
        bit_group_members(point)  # validates the bit list and names
        cls = _ByteSwappedNumberField if point.get(CONF_BYTE_SWAP) else NumberField
        return (
            cls(
                address,
                count=BIT_GROUP_WIDTH[data_type] // 16,
                signed=False,
                word_order=point.get(CONF_WORD_ORDER, "big"),
                writable=False,
            ),
            register_type,
        )

    bit = point.get(CONF_BIT)
    if bit is not None and platform in ("binary_sensor", "switch"):
        return PackedBitField(address, int(bit), writable=writable), register_type

    data_type = point.get(CONF_DATA_TYPE, DT_UINT16)
    byte_swap = bool(point.get(CONF_BYTE_SWAP))
    word_order = point.get(CONF_WORD_ORDER, "big")
    scale = float(point.get(CONF_SCALE, 1.0) or 1.0)
    offset = float(point.get(CONF_OFFSET, 0.0) or 0.0)

    if data_type == DT_STRING:
        cls = _ByteSwappedStringField if byte_swap else StringField
        return (
            cls(address, count=int(point.get(CONF_LENGTH) or 1), writable=False),
            register_type,
        )
    if data_type in _FLOAT_TYPES:
        cls = _ByteSwappedFloatField if byte_swap else FloatField
        return (
            cls(
                address,
                count=_FLOAT_TYPES[data_type],
                word_order=word_order,
                scale=scale,
                offset=offset,
                writable=writable,
                force_fc16=force_fc16,
            ),
            register_type,
        )
    if data_type in _INT_TYPES:
        count, signed = _INT_TYPES[data_type]
        cls = _ByteSwappedNumberField if byte_swap else NumberField
        return (
            cls(
                address,
                count=count,
                signed=signed,
                word_order=word_order,
                scale=scale,
                offset=offset,
                writable=writable,
                force_fc16=force_fc16,
            ),
            register_type,
        )
    raise ValueError(f"unknown data type {data_type!r}")


@dataclass
class UpdateResult:
    """Values read in one poll, and the points that could not be read."""

    values: dict[str, Any] = field(default_factory=dict)
    failed: dict[str, Exception] = field(default_factory=dict)


class ModbusUniversalDevice:
    """A Modbus unit whose register map is defined at runtime."""

    def __init__(
        self,
        unit: ModbusUnit,
        points: Mapping[str, Mapping[str, Any]],
        *,
        address_base: int = 0,
        max_gap: int = 16,
    ) -> None:
        """Build the read plan for every configured point.

        Points with an invalid description are skipped and reported in
        ``invalid``.
        """
        self.unit = unit
        self._address_base = address_base
        self._max_gap = max_gap
        self._pooled = ManualComponent(unit, max_gap=max_gap)
        self._targets: dict[str, tuple[Any, str | None]] = {}
        self._single: dict[str, ManualComponent] = {}
        self._pooled_works = True
        self.invalid: dict[str, str] = {}
        for key, point in points.items():
            try:
                target, space = build_target(point, address_base)
            except (ValueError, KeyError, TypeError) as err:
                self.invalid[key] = str(err)
                continue
            self._targets[key] = (target, space)
            self._pooled.add(key, target, space=space)

    @property
    def keys(self) -> frozenset[str]:
        """The keys of the points that will be polled."""
        return frozenset(self._targets)

    def _component_for(self, key: str) -> ManualComponent:
        """A component that reads only this point (isolates a bad address)."""
        if (component := self._single.get(key)) is None:
            target, space = self._targets[key]
            component = ManualComponent(self.unit, max_gap=0)
            component.add(key, target, space=space)
            self._single[key] = component
        return component

    async def async_update(self) -> UpdateResult:
        """Read every point.

        Reads are pooled into as few requests as possible. When the device
        refuses a pooled block (typically one misconfigured address), every
        point is read on its own so the rest keep working.

        Raises ``ModbusError`` when the link itself fails.
        """
        if not self._targets:
            return UpdateResult()
        if self._pooled_works:
            try:
                return UpdateResult(values=await self._pooled.async_update())
            except ModbusExceptionError as err:
                _LOGGER.info(
                    "Device refused a pooled read (%s); reading registers one by one",
                    err,
                )
                self._pooled_works = False
        result = UpdateResult()
        for key in self._targets:
            try:
                values = await self._component_for(key).async_update()
            except ModbusExceptionError as err:
                result.failed[key] = err
            else:
                result.values[key] = values.get(key)
        if not result.failed:
            # The device answers everything again: go back to pooled reads.
            self._pooled_works = True
        return result

    async def async_write(self, key: str, value: Any) -> None:
        """Write one writable point.

        Raises ``ModbusError`` on failure and ``AttributeError`` for a
        read-only point.
        """
        await self._pooled.write(key, value)

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Return the raw register map for diagnostics."""
        return await self._pooled.async_read_raw(notify=False)


async def async_read_point(
    unit: ModbusUnit, point: Mapping[str, Any], address_base: int = 0
) -> Any:
    """Read a single point once (used by the "test read" step of the UI).

    Raises ``ValueError`` for an invalid description and ``ModbusError`` when
    the read fails.
    """
    target, space = build_target(point, address_base)
    component = ManualComponent(unit, max_gap=0)
    component.add("probe", target, space=space)
    return (await component.async_update(notify=False)).get("probe")
