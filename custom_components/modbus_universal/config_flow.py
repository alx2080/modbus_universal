"""Config flow for Modbus Universal.

* The config entry is one Modbus device: how to reach it and its unit id.
* Every register is a config subentry ("+ Add register" on the device card),
  created and edited entirely in the UI.
* The options flow holds polling settings and can copy the register map of
  another device, so a second identical device takes one click.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from modbus_connection import (
    GatewayPathUnavailableError,
    GatewayTargetError,
    ModbusError,
    ModbusExceptionError,
)

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberDeviceClass, NumberMode
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

try:  # Home Assistant 2026.x moved from voluptuous to probatio
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

try:
    from homeassistant.helpers.selector import SerialPortSelector
except ImportError:  # older Home Assistant: plain text field
    SerialPortSelector = None

from .connection import temporary_unit
from .const import (
    CONF_ADDRESS,
    CONF_ADDRESS_BASE,
    CONF_BAUDRATE,
    CONF_BIT,
    CONF_BIT_NAMES,
    CONF_BITS,
    CONF_BYTE_SWAP,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_DATA_TYPE,
    CONF_FAST_POLL,
    CONF_FAST_SCAN_INTERVAL,
    CONF_FORCE_FC16,
    CONF_FRAMER,
    CONF_INVERT,
    CONF_LENGTH,
    CONF_LINK_TIMEOUT,
    CONF_MAX,
    CONF_MAX_GAP,
    CONF_MESSAGE_SPACING,
    CONF_MIN,
    CONF_OFF_VALUE,
    CONF_OFFSET,
    CONF_ON_VALUE,
    CONF_OPTIONS,
    CONF_PARITY,
    CONF_PLATFORM,
    CONF_PRECISION,
    CONF_PROBE_ADDRESS,
    CONF_PROBE_REGISTER_TYPE,
    CONF_REGISTER_TYPE,
    CONF_SCALE,
    CONF_SCAN_INTERVAL,
    CONF_SOURCE_ENTRY,
    CONF_STEP,
    CONF_STOPBITS,
    CONF_TEST_READ,
    CONF_TIMEOUT,
    CONF_UNIT_ID,
    CONF_WORD_ORDER,
    CONNECTION_TYPES,
    DEFAULT_ADDRESS_BASE,
    DEFAULT_BAUDRATE,
    DEFAULT_FAST_SCAN_INTERVAL,
    DEFAULT_LINK_TIMEOUT,
    DEFAULT_MAX_GAP,
    DEFAULT_MESSAGE_SPACING,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    DT_INT16,
    DT_STRING,
    DT_UINT16,
    DT_UINT32,
    BIT_GROUP_DATA_TYPES,
    INTEGER_16_DATA_TYPES,
    PLATFORM_BIT_GROUP,
    NUMERIC_DATA_TYPES,
    REG_COIL,
    REG_DISCRETE,
    REG_HOLDING,
    REG_INPUT,
    SUBENTRY_REGISTER,
    TYPE_RTU_OVER_TCP,
    TYPE_SERIAL,
    TYPE_TCP,
    TYPE_UDP,
)
from .device import (
    async_read_point,
    bit_group_members,
    build_target,
    split_bit_label,
)
from .helpers import (
    CONF_DEVICE,
    CONF_HOST,
    CONF_PORT,
    build_params,
    parse_options,
    unique_id_for,
)

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_CLASS = "device_class"
CONF_STATE_CLASS = "state_class"
CONF_UNIT_OF_MEASUREMENT = "unit_of_measurement"
CONF_MODE = "mode"

PLATFORMS = ("sensor", "binary_sensor", "bit_group", "switch", "number", "select")

COMMON_UNITS = [
    "°C", "°F", "%", "V", "mV", "A", "mA", "W", "kW", "VA", "var", "Wh", "kWh",
    "Hz", "bar", "Pa", "kPa", "m³", "m³/h", "L", "L/min", "rpm", "s", "min", "h",
    "ppm", "lx",
]  # fmt: skip


# --------------------------------------------------------------------------
# Selector helpers
# --------------------------------------------------------------------------


def _select(options: list[str], key: str | None = None, custom: bool = False) -> SelectSelector:
    config = SelectSelectorConfig(
        options=options,
        mode=SelectSelectorMode.DROPDOWN,
        custom_value=custom,
        sort=key is None and not custom,
    )
    if key is not None:
        config["translation_key"] = key
    return SelectSelector(config)


def _number(
    min_: float | None = None,
    max_: float | None = None,
    step: float | str = 1,
    unit: str | None = None,
) -> NumberSelector:
    config = NumberSelectorConfig(step=step, mode=NumberSelectorMode.BOX)
    if min_ is not None:
        config["min"] = min_
    if max_ is not None:
        config["max"] = max_
    if unit is not None:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _int(value: Any) -> int:
    return int(float(value))


ADDRESS = vol.All(_number(0, 65535), vol.Coerce(_int))
UNIT_ID = vol.All(_number(0, 255), vol.Coerce(_int))
PORT = vol.All(_number(1, 65535), vol.Coerce(_int))
BAUDRATE = vol.All(
    SelectSelector(
        SelectSelectorConfig(
            options=["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"],
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    ),
    vol.Coerce(_int),
)


def _suggested(defaults: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Pre-fill an optional field without making it a hard default."""
    if defaults.get(key) is None:
        return {}
    return {"suggested_value": defaults[key]}


# --------------------------------------------------------------------------
# Connection schemas (config entry)
# --------------------------------------------------------------------------


def _probe_fields(d: Mapping[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(CONF_PROBE_ADDRESS, description=_suggested(d, CONF_PROBE_ADDRESS)): ADDRESS,
        vol.Optional(
            CONF_PROBE_REGISTER_TYPE, default=d.get(CONF_PROBE_REGISTER_TYPE, REG_HOLDING)
        ): _select(
            [REG_HOLDING, REG_INPUT, REG_COIL, REG_DISCRETE], "register_type"
        ),
    }


def connection_schema(kind: str, d: Mapping[str, Any], *, reconfigure: bool) -> vol.Schema:
    """The form for one connection type, pre-filled with ``d``."""
    fields: dict[Any, Any] = {}
    if not reconfigure:
        fields[vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Modbus device"))] = (
            TextSelector()
        )
    if kind == TYPE_SERIAL:
        fields[vol.Required(CONF_DEVICE, default=d.get(CONF_DEVICE, "/dev/ttyUSB0"))] = (
            SerialPortSelector() if SerialPortSelector is not None else TextSelector()
        )
    else:
        fields[vol.Required(CONF_HOST, default=d.get(CONF_HOST, ""))] = TextSelector()
        fields[vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT))] = PORT
    if kind in (TYPE_SERIAL, TYPE_RTU_OVER_TCP):
        fields[
            vol.Required(CONF_BAUDRATE, default=str(d.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)))
        ] = BAUDRATE
    if kind == TYPE_SERIAL:
        fields[vol.Required(CONF_BYTESIZE, default=str(d.get(CONF_BYTESIZE, 8)))] = vol.All(
            _select(["7", "8"]), vol.Coerce(int)
        )
        # Translation keys must be lower case; the entry stores "N"/"E"/"O".
        fields[
            vol.Required(CONF_PARITY, default=str(d.get(CONF_PARITY, "N")).lower())
        ] = _select(["n", "e", "o"], "parity")
        fields[vol.Required(CONF_STOPBITS, default=str(d.get(CONF_STOPBITS, 1)))] = vol.All(
            _select(["1", "2"]), vol.Coerce(int)
        )
    if kind in (TYPE_SERIAL, TYPE_RTU_OVER_TCP):
        fields[vol.Required(CONF_FRAMER, default=d.get(CONF_FRAMER, "rtu"))] = _select(
            ["rtu", "ascii"], "framer"
        )
    fields[vol.Required(CONF_UNIT_ID, default=d.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))] = UNIT_ID
    fields.update(_probe_fields(d))
    return vol.Schema(fields)


async def _async_probe(hass, data: Mapping[str, Any], probe: Mapping[str, Any]) -> None:
    """Read one register to prove the device answers (only if asked to).

    A Modbus exception response (illegal function, illegal address, ...) still
    proves the device is reachable, so only a missing answer fails the probe.
    A gateway reporting that the device behind it is silent counts as missing.

    Raises ``ModbusError`` or ``HomeAssistantError``.
    """
    if probe.get(CONF_PROBE_ADDRESS) is None:
        return
    params = build_params(data)
    async with temporary_unit(hass, params, int(data[CONF_UNIT_ID])) as unit:
        address = int(probe[CONF_PROBE_ADDRESS])
        reader = {
            REG_HOLDING: unit.read_holding_registers,
            REG_INPUT: unit.read_input_registers,
            REG_COIL: unit.read_coils,
            REG_DISCRETE: unit.read_discrete_inputs,
        }[probe.get(CONF_PROBE_REGISTER_TYPE, REG_HOLDING)]
        try:
            await reader(address, 1)
        except (GatewayPathUnavailableError, GatewayTargetError):
            raise
        except ModbusExceptionError as err:
            _LOGGER.info(
                "Probe at %s refused (%s), but the device answered: accepting", address, err
            )


# --------------------------------------------------------------------------
# Config flow: the device
# --------------------------------------------------------------------------


class ModbusUniversalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Modbus device."""

    VERSION = 1

    def __init__(self) -> None:
        self._kind: str = TYPE_TCP

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ModbusUniversalOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_REGISTER: RegisterSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick how the device is connected."""
        return self.async_show_menu(step_id="user", menu_options=list(CONNECTION_TYPES))

    async def async_step_tcp(self, user_input=None) -> ConfigFlowResult:
        return await self._async_connection_step(TYPE_TCP, user_input)

    async def async_step_rtu_over_tcp(self, user_input=None) -> ConfigFlowResult:
        return await self._async_connection_step(TYPE_RTU_OVER_TCP, user_input)

    async def async_step_serial(self, user_input=None) -> ConfigFlowResult:
        return await self._async_connection_step(TYPE_SERIAL, user_input)

    async def async_step_udp(self, user_input=None) -> ConfigFlowResult:
        return await self._async_connection_step(TYPE_UDP, user_input)

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Change how an existing device is reached."""
        kind = self._get_reconfigure_entry().data[CONF_CONNECTION_TYPE]
        return await self._async_connection_step(kind, None)

    async def _async_connection_step(
        self, kind: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        reconfigure = self.source == SOURCE_RECONFIGURE
        defaults: dict[str, Any] = (
            dict(self._get_reconfigure_entry().data) if reconfigure else {}
        )
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            defaults = dict(user_input)
            probe = {
                k: user_input.pop(k)
                for k in (CONF_PROBE_ADDRESS, CONF_PROBE_REGISTER_TYPE)
                if k in user_input
            }
            name = user_input.pop(CONF_NAME, None)
            data = {CONF_CONNECTION_TYPE: kind, **user_input}
            if CONF_PARITY in data:
                data[CONF_PARITY] = str(data[CONF_PARITY]).upper()
            try:
                params = build_params(data)
            except ValueError:
                errors["base"] = "invalid_connection"
            else:
                unique_id = unique_id_for(params, int(data[CONF_UNIT_ID]))
                try:
                    await _async_probe(self.hass, data, probe)
                except ModbusError as err:
                    errors["base"] = "cannot_connect"
                    placeholders["error"] = str(err)
                except HomeAssistantError as err:
                    errors["base"] = "link_conflict"
                    placeholders["error"] = str(err)
            if not errors:
                if reconfigure:
                    entry = self._get_reconfigure_entry()
                    if unique_id != entry.unique_id:
                        await self.async_set_unique_id(unique_id)
                        self._abort_if_unique_id_configured()
                    return self.async_update_reload_and_abort(
                        entry, unique_id=unique_id, data=data
                    )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name or "Modbus device",
                    data=data,
                    options={
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_FAST_SCAN_INTERVAL: DEFAULT_FAST_SCAN_INTERVAL,
                        CONF_LINK_TIMEOUT: DEFAULT_LINK_TIMEOUT,
                        CONF_TIMEOUT: DEFAULT_TIMEOUT,
                        CONF_MESSAGE_SPACING: DEFAULT_MESSAGE_SPACING,
                        CONF_MAX_GAP: DEFAULT_MAX_GAP,
                        CONF_ADDRESS_BASE: DEFAULT_ADDRESS_BASE,
                    },
                )

        return self.async_show_form(
            step_id=kind,
            data_schema=connection_schema(kind, defaults, reconfigure=reconfigure),
            errors=errors,
            description_placeholders=placeholders,
        )


# --------------------------------------------------------------------------
# Options flow: polling settings + copy registers from another device
# --------------------------------------------------------------------------


class ModbusUniversalOptionsFlow(OptionsFlow):
    """Device settings."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "copy_from"])

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(_number(0.1, 86400, 0.1, "s"), vol.Coerce(float)),
                vol.Required(
                    CONF_FAST_SCAN_INTERVAL,
                    default=o.get(CONF_FAST_SCAN_INTERVAL, DEFAULT_FAST_SCAN_INTERVAL),
                ): vol.All(_number(0.05, 3600, 0.05, "s"), vol.Coerce(float)),
                vol.Required(
                    CONF_TIMEOUT, default=o.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
                ): vol.All(_number(0.1, 60, 0.1, "s"), vol.Coerce(float)),
                vol.Required(
                    CONF_LINK_TIMEOUT, default=o.get(CONF_LINK_TIMEOUT, DEFAULT_LINK_TIMEOUT)
                ): vol.All(_number(0.5, 86400, 0.5, "s"), vol.Coerce(float)),
                vol.Required(
                    CONF_MESSAGE_SPACING,
                    default=o.get(CONF_MESSAGE_SPACING, DEFAULT_MESSAGE_SPACING),
                ): vol.All(_number(0, 5, 0.01, "s"), vol.Coerce(float)),
                vol.Required(
                    CONF_MAX_GAP, default=o.get(CONF_MAX_GAP, DEFAULT_MAX_GAP)
                ): vol.All(_number(0, 100), vol.Coerce(_int)),
                vol.Required(
                    CONF_ADDRESS_BASE,
                    default=str(o.get(CONF_ADDRESS_BASE, DEFAULT_ADDRESS_BASE)),
                ): vol.All(_select(["0", "1"], "address_base"), vol.Coerce(int)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_copy_from(self, user_input=None) -> ConfigFlowResult:
        """Copy every register of another device into this one."""
        sources = [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != self.config_entry.entry_id
            and any(s.subentry_type == SUBENTRY_REGISTER for s in entry.subentries.values())
        ]
        if not sources:
            return self.async_abort(reason="no_source")
        if user_input is not None:
            source = self.hass.config_entries.async_get_entry(user_input[CONF_SOURCE_ENTRY])
            if source is not None:
                for subentry in source.subentries.values():
                    if subentry.subentry_type != SUBENTRY_REGISTER:
                        continue
                    self.hass.config_entries.async_add_subentry(
                        self.config_entry,
                        ConfigSubentry(
                            data=dict(subentry.data),
                            subentry_type=SUBENTRY_REGISTER,
                            title=subentry.title,
                            unique_id=None,
                        ),
                    )
            return self.async_create_entry(data=dict(self.config_entry.options))
        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_ENTRY): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=e.entry_id, label=e.title) for e in sources
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="copy_from", data_schema=schema)


# --------------------------------------------------------------------------
# Subentry flow: one register = one entity
# --------------------------------------------------------------------------


def register_schema(platform: str, d: Mapping[str, Any]) -> vol.Schema:
    """The form describing one register for ``platform``, pre-filled with ``d``."""
    f: dict[Any, Any] = {vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): TextSelector()}

    def reg_type(options: list[str], default: str) -> None:
        f[vol.Required(CONF_REGISTER_TYPE, default=d.get(CONF_REGISTER_TYPE, default))] = (
            _select(options, "register_type")
        )

    def address() -> None:
        f[vol.Required(CONF_ADDRESS, default=d.get(CONF_ADDRESS, 0))] = ADDRESS

    def encoding(types: list[str], default: str, scaling: bool = True) -> None:
        f[vol.Required(CONF_DATA_TYPE, default=d.get(CONF_DATA_TYPE, default))] = _select(
            types, "data_type"
        )
        if DT_STRING in types:
            f[vol.Optional(CONF_LENGTH, description=_suggested(d, CONF_LENGTH))] = vol.All(
                _number(1, 125), vol.Coerce(_int)
            )
        if any(t not in INTEGER_16_DATA_TYPES for t in types):
            f[vol.Required(CONF_WORD_ORDER, default=d.get(CONF_WORD_ORDER, "big"))] = (
                _select(["big", "little"], "word_order")
            )
        f[vol.Required(CONF_BYTE_SWAP, default=d.get(CONF_BYTE_SWAP, False))] = (
            BooleanSelector()
        )
        if scaling:
            f[vol.Required(CONF_SCALE, default=d.get(CONF_SCALE, 1.0))] = vol.All(
                _number(step="any"), vol.Coerce(float)
            )
            f[vol.Required(CONF_OFFSET, default=d.get(CONF_OFFSET, 0.0))] = vol.All(
                _number(step="any"), vol.Coerce(float)
            )

    def bit() -> None:
        f[vol.Optional(CONF_BIT, description=_suggested(d, CONF_BIT))] = vol.All(
            _number(0, 15), vol.Coerce(_int)
        )

    def unit_field() -> None:
        f[
            vol.Optional(
                CONF_UNIT_OF_MEASUREMENT, description=_suggested(d, CONF_UNIT_OF_MEASUREMENT)
            )
        ] = _select(COMMON_UNITS, custom=True)

    def device_class(values: list[str]) -> None:
        f[vol.Optional(CONF_DEVICE_CLASS, description=_suggested(d, CONF_DEVICE_CLASS))] = (
            _select(sorted(values))
        )

    def fc16() -> None:
        f[vol.Required(CONF_FORCE_FC16, default=d.get(CONF_FORCE_FC16, False))] = (
            BooleanSelector()
        )

    if platform == "sensor":
        reg_type([REG_HOLDING, REG_INPUT], REG_HOLDING)
        address()
        encoding([*NUMERIC_DATA_TYPES, DT_STRING], DT_UINT16)
        f[vol.Optional(CONF_PRECISION, description=_suggested(d, CONF_PRECISION))] = (
            vol.All(_number(0, 6), vol.Coerce(_int))
        )
        unit_field()
        device_class([c.value for c in SensorDeviceClass])
        f[vol.Optional(CONF_STATE_CLASS, description=_suggested(d, CONF_STATE_CLASS))] = (
            _select([c.value for c in SensorStateClass], "state_class")
        )
    elif platform == "binary_sensor":
        reg_type([REG_COIL, REG_DISCRETE, REG_HOLDING, REG_INPUT], REG_DISCRETE)
        address()
        bit()
        f[vol.Required(CONF_INVERT, default=d.get(CONF_INVERT, False))] = BooleanSelector()
        device_class([c.value for c in BinarySensorDeviceClass])
    elif platform == PLATFORM_BIT_GROUP:
        reg_type([REG_HOLDING, REG_INPUT], REG_HOLDING)
        address()
        f[vol.Required(CONF_DATA_TYPE, default=d.get(CONF_DATA_TYPE, DT_UINT32))] = (
            _select(list(BIT_GROUP_DATA_TYPES), "data_type")
        )
        f[vol.Required(CONF_WORD_ORDER, default=d.get(CONF_WORD_ORDER, "big"))] = _select(
            ["big", "little"], "word_order"
        )
        f[vol.Required(CONF_BYTE_SWAP, default=d.get(CONF_BYTE_SWAP, False))] = (
            BooleanSelector()
        )
        f[vol.Optional(CONF_BITS, description=_suggested(d, CONF_BITS))] = TextSelector()
        f[vol.Optional(CONF_BIT_NAMES, description=_suggested(d, CONF_BIT_NAMES))] = (
            TextSelector(TextSelectorConfig(multiline=True))
        )
        f[vol.Required(CONF_INVERT, default=d.get(CONF_INVERT, False))] = BooleanSelector()
        device_class([c.value for c in BinarySensorDeviceClass])
    elif platform == "switch":
        reg_type([REG_COIL, REG_HOLDING], REG_COIL)
        address()
        bit()
        f[vol.Required(CONF_ON_VALUE, default=d.get(CONF_ON_VALUE, 1))] = vol.All(
            _number(0, 65535), vol.Coerce(_int)
        )
        f[vol.Required(CONF_OFF_VALUE, default=d.get(CONF_OFF_VALUE, 0))] = vol.All(
            _number(0, 65535), vol.Coerce(_int)
        )
        f[vol.Required(CONF_INVERT, default=d.get(CONF_INVERT, False))] = BooleanSelector()
        fc16()
    elif platform == "number":
        address()
        encoding(list(NUMERIC_DATA_TYPES), DT_UINT16)
        f[vol.Required(CONF_MIN, default=d.get(CONF_MIN, 0))] = vol.All(
            _number(step="any"), vol.Coerce(float)
        )
        f[vol.Required(CONF_MAX, default=d.get(CONF_MAX, 100))] = vol.All(
            _number(step="any"), vol.Coerce(float)
        )
        f[vol.Required(CONF_STEP, default=d.get(CONF_STEP, 1))] = vol.All(
            _number(step="any"), vol.Coerce(float)
        )
        f[vol.Required(CONF_MODE, default=d.get(CONF_MODE, NumberMode.BOX.value))] = (
            _select([m.value for m in NumberMode], "number_mode")
        )
        unit_field()
        device_class([c.value for c in NumberDeviceClass])
        fc16()
    elif platform == "select":
        address()
        encoding([DT_UINT16, DT_INT16], DT_UINT16, scaling=False)
        f[vol.Required(CONF_OPTIONS, default=d.get(CONF_OPTIONS, "0=Off\n1=On"))] = (
            TextSelector(TextSelectorConfig(multiline=True))
        )
        fc16()

    f[vol.Required(CONF_FAST_POLL, default=d.get(CONF_FAST_POLL, False))] = (
        BooleanSelector()
    )
    f[vol.Required(CONF_TEST_READ, default=False)] = BooleanSelector()
    return vol.Schema(f)


def _describe_bits(data: Mapping[str, Any], value: Any) -> str:
    """The raw value and the state of each bit, for the test-read step."""
    if value is None:
        return "None"
    raw = int(value)
    lines = [f"0x{raw:X} ({raw})", ""]
    for bit, name in bit_group_members(data):
        label, device_class, invert = split_bit_label(name)
        on = bool((raw >> bit) & 1) != (invert != bool(data.get(CONF_INVERT)))
        state = "ON" if on else "OFF"
        extra = f" [{device_class}]" if device_class else ""
        lines.append(f"- {bit}: {state}" + (f" — {label}" if label else "") + extra)
    return "\n".join(lines)


def validate_register(platform: str, data: dict[str, Any]) -> str | None:
    """Return an error key, or ``None`` when the description is consistent."""
    register_type = data.get(CONF_REGISTER_TYPE, REG_HOLDING)
    if platform == "binary_sensor" and register_type in (REG_HOLDING, REG_INPUT):
        if data.get(CONF_BIT) is None:
            return "bit_required"
    if platform == PLATFORM_BIT_GROUP:
        try:
            members = bit_group_members(data)
        except ValueError:
            return "invalid_bits"
        classes = {c.value for c in BinarySensorDeviceClass}
        for _, label in members:
            if (device_class := split_bit_label(label)[1]) and device_class not in classes:
                return "invalid_bit_class"
    if data.get(CONF_DATA_TYPE) == DT_STRING and not data.get(CONF_LENGTH):
        return "length_required"
    if platform == "number" and data[CONF_MIN] >= data[CONF_MAX]:
        return "invalid_range"
    if platform == "select":
        try:
            parse_options(data[CONF_OPTIONS])
        except ValueError:
            return "invalid_options"
    if data.get(CONF_SCALE) == 0:
        return "invalid_scale"
    try:
        build_target(data)
    except (ValueError, TypeError):
        return "invalid_register"
    return None


class RegisterSubentryFlow(ConfigSubentryFlow):
    """Add or edit one register of a device."""

    def __init__(self) -> None:
        self._platform: str | None = None
        self._pending: tuple[str, dict[str, Any]] | None = None

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        """Choose what the register becomes in Home Assistant."""
        return self.async_show_menu(step_id="user", menu_options=list(PLATFORMS))

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        self._platform = subentry.data[CONF_PLATFORM]
        return await self._async_register_step(self._platform, None)

    async def async_step_sensor(self, user_input=None) -> SubentryFlowResult:
        return await self._async_register_step("sensor", user_input)

    async def async_step_binary_sensor(self, user_input=None) -> SubentryFlowResult:
        return await self._async_register_step("binary_sensor", user_input)

    async def async_step_bit_group(self, user_input=None) -> SubentryFlowResult:
        return await self._async_register_step(PLATFORM_BIT_GROUP, user_input)

    async def async_step_switch(self, user_input=None) -> SubentryFlowResult:
        return await self._async_register_step("switch", user_input)

    async def async_step_number(self, user_input=None) -> SubentryFlowResult:
        return await self._async_register_step("number", user_input)

    async def async_step_select(self, user_input=None) -> SubentryFlowResult:
        return await self._async_register_step("select", user_input)

    async def _async_register_step(
        self, platform: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        reconfigure = self.source == SOURCE_RECONFIGURE
        if user_input is None and reconfigure:
            subentry = self._get_reconfigure_subentry()
            defaults: dict[str, Any] = {**subentry.data, CONF_NAME: subentry.title}
        else:
            defaults = dict(user_input or {})
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            test_read = user_input.pop(CONF_TEST_READ, False)
            name = user_input.pop(CONF_NAME).strip()
            data = {CONF_PLATFORM: platform, **user_input}
            if platform == "number":
                data[CONF_REGISTER_TYPE] = REG_HOLDING
            if platform == "select":
                data[CONF_REGISTER_TYPE] = REG_HOLDING
            if (error := validate_register(platform, data)) is not None:
                errors["base"] = error
            elif test_read:
                value, error, text = await self._async_test_read(data)
                if error is None:
                    if platform == PLATFORM_BIT_GROUP:
                        value = _describe_bits(data, value)
                    self._pending = (name, data)
                    return self.async_show_form(
                        step_id=(
                            "bit_test_result"
                            if platform == PLATFORM_BIT_GROUP
                            else "test_result"
                        ),
                        data_schema=vol.Schema({}),
                        description_placeholders={"name": name, "value": str(value)},
                    )
                errors["base"] = error
                placeholders["error"] = text
            else:
                return self._async_save(name, data)

        return self.async_show_form(
            step_id=platform,
            data_schema=register_schema(platform, defaults),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_test_result(self, user_input=None) -> SubentryFlowResult:
        """The value looked right: save the register."""
        assert self._pending is not None
        name, data = self._pending
        return self._async_save(name, data)

    async def async_step_bit_test_result(self, user_input=None) -> SubentryFlowResult:
        """The bits looked right: save the bit group."""
        return await self.async_step_test_result(user_input)

    async def _async_test_read(self, data: dict[str, Any]) -> tuple[Any, str | None, str]:
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return None, "not_loaded", ""
        try:
            value = await async_read_point(
                entry.runtime_data.unit,
                data,
                int(entry.options.get(CONF_ADDRESS_BASE, DEFAULT_ADDRESS_BASE)),
            )
        except ModbusError as err:
            return None, "read_failed", str(err)
        except ValueError as err:
            return None, "invalid_register", str(err)
        return value, None, ""

    @callback
    def _async_save(self, name: str, data: dict[str, Any]) -> SubentryFlowResult:
        title = name or f"{data[CONF_PLATFORM]} {data.get(CONF_ADDRESS)}"
        if data[CONF_PLATFORM] == PLATFORM_BIT_GROUP:
            # Optional text fields left empty must not keep their old value.
            data.setdefault(CONF_BITS, "")
            data.setdefault(CONF_BIT_NAMES, "")
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=title,
                data=data,
            )
        return self.async_create_entry(title=title, data=data)
