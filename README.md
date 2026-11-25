# Modbus Universal

**English** | [Українська](README.uk.md)

A Home Assistant custom integration for **any** Modbus device. The connection and all registers are set up in the browser, without YAML. Under the hood it uses the new Home Assistant infrastructure: shared connections of the `modbus` integration (`async_get_unit`) and the [`modbus-connection`](https://home-assistant-libs.github.io/modbus-connection/) library (`ManualComponent` — a register layout known only at run time).

## Features

- **Connections:** Modbus TCP, RTU over TCP (transparent RS485 → Ethernet/Wi-Fi converters), serial port RTU/ASCII, Modbus UDP.
- **One device = one entry** (Settings → Devices & services → Add integration → Modbus Universal). Several devices on one RS485 bus or behind one gateway share one connection automatically: requests queue up instead of competing.
- **Each register = a subentry**, added with **+ Add register** on the device card. A register can be edited or deleted there as well; its entity is created and deleted with it.
- **Entity types:** sensor, binary sensor, bit group (one register — several binary sensors), switch, number (setpoints), select (value ↔ mode).
- **Data types:** int16/uint16/int32/uint32/int64/uint64/float32/float64, strings; word order (ABCD/CDAB), byte swap, scale, offset, single bits of a register (reading and writing a bit without spoiling the others), coils and discrete inputs, forced writing with function 16.
- **Fast polling of individual registers:** the "Fast polling" switch of a register plus "Fast scan interval" in the device options (for example 0.2 s = 5 times per second). The other registers are read at the normal interval; both polls use one connection and do not disturb each other.
- **Link status:** each device has a "Connection" binary sensor (connectivity). If there was no successful read for longer than "Connection lost after" seconds, it switches to "Disconnected". The `last_seen` attribute holds the time of the device's last answer. The sensor itself never becomes unavailable, which makes it handy for automations.
- **Test read** when adding a register: the current value is shown before saving.
- **Copying the register map** from another device (Options → "Copy registers from another device"): a second identical device is set up in a minute.
- **Group reads:** neighbouring registers are read with one request. If the device refuses the group request (usually because of one wrong address), the integration switches to reading one by one, so only the faulty register becomes unavailable.
- Register numbering from 0 or from 1, polling interval, timeout, pause between requests, automatic reconnection, diagnostics with raw values.

## Installation with HACS

1. HACS → ⋮ (top right) → **Custom repositories**.
2. Repository: `https://github.com/alx2080/modbus_universal`, Type: **Integration** → **Add**.
3. Find the integration in HACS → **Download** → restart Home Assistant.

HACS offers new versions as ordinary updates.

## Manual installation

1. Copy the folder `custom_components/modbus_universal` to `config/custom_components/` (or add the repository to HACS as a custom one).
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → Modbus Universal.

Supported versions: Home Assistant 2025.8+ (subentries are needed). Shared connections through `async_get_unit` are used if your Home Assistant version has them; on older versions the integration opens its own connection.

## Usage

1. Add a device: connection type → address/port → Unit ID. Fill in "Test register address" if you want the connection to be checked.
2. On the integration page press **+ Add register** at the device, choose the entity type and fill in the address, data type, scale and so on. Turn on "Read the register before saving" to see the value right away.
3. To edit a register use ⋮ → Edit register; to delete it use ⋮ → Delete.

Examples:

| What | Entity type | Settings |
| --- | --- | --- |
| Temperature 215 = 21.5 °C | Sensor | holding, int16, scale 0.1, °C |
| Energy meter, Wh | Sensor | input, uint32, CDAB order if needed, state class `total_increasing` |
| Alarm = bit 3 of register 40 | Binary sensor | holding, address 40, bit 3 |
| Relay | Switch | coil |
| Mode 0/1/2 | Select | holding, `0=Off`, `1=Auto`, `2=Heat` |

## Limitations and notes

- If the same device is already set up in the YAML configuration `modbus:`, that uses a separate connection. Remove it from YAML to avoid competing requests.
- Core integrations of Home Assistant must keep device code in a separate PyPI library. This is not required for a custom integration, so the device layer lives in `device.py` (without Home Assistant imports).
