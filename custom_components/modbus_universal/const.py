"""Constants for the Modbus Universal integration."""

from typing import Final

DOMAIN: Final = "modbus_universal"

# --- Connection (config entry data) -----------------------------------------
CONF_CONNECTION_TYPE: Final = "connection_type"
CONF_UNIT_ID: Final = "unit_id"
CONF_BAUDRATE: Final = "baudrate"
CONF_BYTESIZE: Final = "bytesize"
CONF_PARITY: Final = "parity"
CONF_STOPBITS: Final = "stopbits"
CONF_FRAMER: Final = "framer"
CONF_PROBE_ADDRESS: Final = "probe_address"
CONF_PROBE_REGISTER_TYPE: Final = "probe_register_type"

TYPE_TCP: Final = "tcp"
TYPE_UDP: Final = "udp"
TYPE_SERIAL: Final = "serial"
TYPE_RTU_OVER_TCP: Final = "rtu_over_tcp"
CONNECTION_TYPES: Final = (TYPE_TCP, TYPE_RTU_OVER_TCP, TYPE_SERIAL, TYPE_UDP)

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1
DEFAULT_BAUDRATE: Final = 9600

# --- Device options (config entry options) ----------------------------------
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_FAST_SCAN_INTERVAL: Final = "fast_scan_interval"
CONF_TIMEOUT: Final = "timeout"
CONF_MESSAGE_SPACING: Final = "message_spacing"
CONF_MAX_GAP: Final = "max_gap"
CONF_ADDRESS_BASE: Final = "address_base"
CONF_SOURCE_ENTRY: Final = "source_entry"
CONF_LINK_TIMEOUT: Final = "link_timeout"

DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_FAST_SCAN_INTERVAL: Final = 1.0
DEFAULT_TIMEOUT: Final = 3.0
DEFAULT_MESSAGE_SPACING: Final = 0.0
DEFAULT_MAX_GAP: Final = 16
DEFAULT_ADDRESS_BASE: Final = 0
DEFAULT_LINK_TIMEOUT: Final = 10.0

# --- Registers (config subentries) ------------------------------------------
SUBENTRY_REGISTER: Final = "register"

CONF_PLATFORM: Final = "platform"
CONF_REGISTER_TYPE: Final = "register_type"
CONF_ADDRESS: Final = "address"
CONF_DATA_TYPE: Final = "data_type"
CONF_WORD_ORDER: Final = "word_order"
CONF_BYTE_SWAP: Final = "byte_swap"
CONF_SCALE: Final = "scale"
CONF_OFFSET: Final = "offset"
CONF_PRECISION: Final = "precision"
CONF_LENGTH: Final = "length"
CONF_BIT: Final = "bit"
CONF_INVERT: Final = "invert"
CONF_ON_VALUE: Final = "on_value"
CONF_OFF_VALUE: Final = "off_value"
CONF_MIN: Final = "min"
CONF_MAX: Final = "max"
CONF_STEP: Final = "step"
CONF_OPTIONS: Final = "options"
CONF_FORCE_FC16: Final = "force_fc16"
CONF_TEST_READ: Final = "test_read"
CONF_FAST_POLL: Final = "fast_poll"

REG_HOLDING: Final = "holding"
REG_INPUT: Final = "input"
REG_COIL: Final = "coil"
REG_DISCRETE: Final = "discrete"

DT_INT16: Final = "int16"
DT_UINT16: Final = "uint16"
DT_INT32: Final = "int32"
DT_UINT32: Final = "uint32"
DT_INT64: Final = "int64"
DT_UINT64: Final = "uint64"
DT_FLOAT32: Final = "float32"
DT_FLOAT64: Final = "float64"
DT_STRING: Final = "string"

NUMERIC_DATA_TYPES: Final = (
    DT_INT16,
    DT_UINT16,
    DT_INT32,
    DT_UINT32,
    DT_INT64,
    DT_UINT64,
    DT_FLOAT32,
    DT_FLOAT64,
)
INTEGER_16_DATA_TYPES: Final = (DT_UINT16, DT_INT16)

# --- Bit group: one register (16/32/64 bits) shown as a binary sensor per bit
PLATFORM_BIT_GROUP: Final = "bit_group"
CONF_BITS: Final = "bits"
CONF_BIT_NAMES: Final = "bit_names"
BIT_GROUP_DATA_TYPES: Final = (DT_UINT16, DT_UINT32, DT_UINT64)
BIT_GROUP_WIDTH: Final = {DT_UINT16: 16, DT_UINT32: 32, DT_UINT64: 64}
