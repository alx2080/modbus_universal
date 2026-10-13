"""Helpers shared by setup and the config flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modbus_connection import (
    ModbusSerialParams,
    ModbusTcpParams,
    ModbusUdpParams,
)

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_UNIT_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    TYPE_RTU_OVER_TCP,
    TYPE_SERIAL,
    TYPE_TCP,
    TYPE_UDP,
)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE = "device"

type ModbusParams = ModbusTcpParams | ModbusUdpParams | ModbusSerialParams


def build_params(data: Mapping[str, Any]) -> ModbusParams:
    """Build the backend-neutral connection parameters from entry data.

    Raises ``ValueError`` for an unknown connection type.
    """
    kind = data[CONF_CONNECTION_TYPE]
    if kind == TYPE_TCP:
        return ModbusTcpParams(
            host=data[CONF_HOST], port=int(data.get(CONF_PORT, DEFAULT_PORT))
        )
    if kind == TYPE_UDP:
        return ModbusUdpParams(
            host=data[CONF_HOST], port=int(data.get(CONF_PORT, DEFAULT_PORT))
        )
    if kind == TYPE_RTU_OVER_TCP:
        host = data[CONF_HOST]
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        return ModbusSerialParams(
            device=f"socket://{host}:{int(data.get(CONF_PORT, DEFAULT_PORT))}",
            baudrate=int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            framer=data.get(CONF_FRAMER, "rtu"),
        )
    if kind == TYPE_SERIAL:
        return ModbusSerialParams(
            device=data[CONF_DEVICE],
            baudrate=int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            bytesize=int(data.get(CONF_BYTESIZE, 8)),
            parity=str(data.get(CONF_PARITY, "N")).upper(),
            stopbits=int(data.get(CONF_STOPBITS, 1)),
            framer=data.get(CONF_FRAMER, "rtu"),
        )
    raise ValueError(f"unknown connection type {kind!r}")


def unique_id_for(params: ModbusParams, unit_id: int) -> str:
    """A stable id for one unit behind one physical endpoint."""
    return ":".join(str(part) for part in (*params.endpoint, unit_id))


def describe(data: Mapping[str, Any]) -> str:
    """Short human text for the connection, used as the device model."""
    kind = data[CONF_CONNECTION_TYPE]
    unit = data.get(CONF_UNIT_ID)
    if kind == TYPE_SERIAL:
        where = data[CONF_DEVICE]
    else:
        where = f"{data[CONF_HOST]}:{data.get(CONF_PORT, DEFAULT_PORT)}"
    return f"{kind.upper()} {where} #{unit}"


def parse_options(text: str) -> dict[int, str]:
    """Parse ``value=label`` lines (or ``value:label``) for a select entity.

    Raises ``ValueError`` on a malformed line or duplicate value.
    """
    result: dict[int, str] = {}
    for raw_line in text.replace(";", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        sep = "=" if "=" in line else ":"
        if sep not in line:
            raise ValueError(line)
        value, label = line.split(sep, 1)
        number = int(value.strip(), 0)
        label = label.strip()
        if not label or number in result or label in result.values():
            raise ValueError(line)
        result[number] = label
    if not result:
        raise ValueError("empty")
    return result
