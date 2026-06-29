# Davis Vantage Vue — ESPHome RF Receiver

Receives 868 MHz ISM band transmissions from a **Davis Vantage Vue** weather station and publishes decoded observations to MQTT under the project's standard topic namespace.

> **Installation:** Follow the [server installation guide](../README.md#installation) first. The ESPHome firmware is flashed independently — see [Setup](#setup) below.

---

## Hardware

### Receiver board — Sparkle IoT XH-S3E

| Spec | Value |
|---|---|
| SoC | ESP32-S3 |
| Flash | 16 MB |
| PSRAM | 8 MB (Octal SPI) |
| RF module | CC1101 (868 MHz ISM, EU) |

### RF module — GERUI CC1101 868 MHz

A dedicated CC1101 breakout board with integrated antenna. The GERUI board labels its SPI data pins `SI` (MOSI) and `SO` (MISO).

### Wiring — GERUI CC1101 → Sparkle IoT XH-S3E

| GERUI CC1101 pin | ESP32-S3 GPIO | Board label |
|---|---|---|
| VCC | 3.3 V | 3V3 |
| GND | GND | GND |
| SCK | GPIO 12 | 12 |
| SI (MOSI) | GPIO 11 | 11 |
| SO (MISO) | GPIO 13 | 13 |
| CS (CSN) | GPIO 10 | 10 |
| GDO0 | GPIO 9 | 9 |
| GDO2 | — | not connected |

> **Important:** GPIO 26–37 are reserved for internal flash/PSRAM on the N16R8 and must not be used.

### Davis Vantage Vue

- 868 MHz ISM band wireless sensor suite (EU frequency plan)
- Protocol is community-reverse-engineered (not officially documented)
- Transmits wind on every packet; temperature, humidity, gust, and rain each arrive in their own packet type (~every 20-30 s per measurement)

---

## RF Configuration

| Parameter | Value | Notes |
|---|---|---|
| Frequency | 868.35 MHz | Centre of the 5 EU hop channels (868.04–868.52 MHz) |
| Modulation | GFSK | |
| Symbol rate | 19 200 baud | |
| FSK deviation | 9.5 kHz | |
| Filter BW | 325 kHz | Wide enough to capture all hop channels passively |
| Packet length | 8 bytes | Fixed |
| Sync word | `0xCB89` | 16/16 mode |
| CRC | Off | CRC-16/CCITT verified in firmware with bit-shift fallback |

---

## How it works

1. **Packet reception** — CC1101 receives raw 8-byte frames on 868.35 MHz
2. **Bit reversal** — bytes are LSB→MSB reversed to match Davis bit order
3. **CRC validation** — CRC-16/CCITT checked with up to 3 bit-shift attempts to handle alignment
4. **Station lock** — the first valid station ID seen is auto-locked; packets from other stations are silently ignored. Override by setting `known_unit_id` to a specific value (0 = Davis transmitter ID 1, 1 = ID 2, etc.)
5. **Decoding** — packet type byte selects the measurement: wind (every packet), temperature (type 8), gust (type 9), humidity (type 10), rain (type 14)
6. **Publishing** — consolidated `observation` payload published on every packet using the latest known values for all fields

---

## MQTT Topics

All topics are under `weatherdatalogger/davis-<id>/` where `<id>` is the locked station unit ID (0–7).

| Topic | Frequency | Content |
|---|---|---|
| `.../observation` | Every packet (~2.5 s) | All latest known values — flat JSON |
| `.../rapid_wind` | Every packet | `wind_avg_ms`, `wind_direction_deg` |
| `.../device_status` | Every packet | `rssi`, `lqi`, `battery_low` |

### Example `observation` payload

```json
{
  "wind_avg_ms": 3.13,
  "wind_direction_deg": 247.1,
  "wind_gust_ms": 5.36,
  "air_temperature_c": 18.2,
  "relative_humidity_pct": 72.0,
  "rain_accumulation_mm": 4.2,
  "battery_low": false
}
```

Fields not yet received since last boot are omitted until the relevant packet type arrives. The DB writer treats missing fields as SQL NULL.

### Field conventions

All field names follow the project standard — descriptive snake_case with SI unit suffix:

| Field | Unit | Notes |
|---|---|---|
| `wind_avg_ms` | m/s | 5-packet moving average applied by ESPHome |
| `wind_gust_ms` | m/s | Peak gust from packet type 9 |
| `wind_direction_deg` | ° | 0–360 |
| `air_temperature_c` | °C | |
| `relative_humidity_pct` | % | |
| `rain_accumulation_mm` | mm | Cumulative since last boot; 0.2 mm per tip |
| `battery_low` | boolean | True when transmitter battery is low |

---

## Setup

### 1. Create `secrets.yaml`

In the same directory as the YAML file (or your ESPHome config directory), create `secrets.yaml`:

```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "YourWiFiPassword"
mqtt_broker: "192.168.1.10"
mqtt_username: "your_mqtt_user"
mqtt_password: "your_mqtt_password"
ha_api_key: "your_32_byte_base64_key"   # generate: openssl rand -base64 32
ota_password: "your_ota_password"
```

### 2. Flash the firmware

Install the ESPHome CLI if not already installed:

```bash
pip install esphome
```

Flash for the first time over USB:

```bash
esphome run davis/davis-vantage-receiver.yaml
```

Subsequent updates can be flashed over Wi-Fi (OTA):

```bash
esphome run davis/davis-vantage-receiver.yaml
```

### 3. Verify

Check ESPHome logs:

```bash
esphome logs davis/davis-vantage-receiver.yaml
```

You should see `Auto-locked to station ID: X` on the first valid packet, then wind readings every ~2.5 s. Verify MQTT output:

```bash
mosquitto_sub -h <broker> -t "weatherdatalogger/davis-#" -v
```

---

## Home Assistant Integration

The ESPHome firmware connects to HA via the **native API** (the `api:` block in the YAML), which auto-discovers these entities:

| Entity | Type | Unit |
|---|---|---|
| Davis Temperature | Sensor | °C |
| Davis Humidity | Sensor | % |
| Davis Wind Speed | Sensor | m/s |
| Davis Wind Gust | Sensor | m/s |
| Davis Daily Rain | Sensor | mm |
| Davis Wind Direction | Text sensor | e.g. `247° WSW` |
| Davis Battery Low | Binary sensor | on/off |
| Davis RSSI | Sensor (diagnostic) | dBm |
| Davis LQI | Sensor (diagnostic) | — |

Wind speed is smoothed with a 5-sample sliding window average. The text sensor shows degrees and the nearest compass point (16-point, English).
