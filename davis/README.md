# Davis Vantage Vue — ESPHome RF Receiver

Receives 868 MHz ISM band transmissions from a **Davis Vantage Vue** weather station and publishes decoded observations to MQTT under the project's standard topic namespace.

> **Installation:** Follow the [server installation guide](../README.md#installation) first. The ESPHome firmware is flashed independently — see [Setup](#setup) below.

---

## Hardware

### Receiver board — ESP32-WROOM-32 (30-pin devkit)

| Spec | Value |
|---|---|
| SoC | ESP32 (Xtensa LX6 dual-core) |
| Flash | 4 MB |
| PSRAM | None |
| RF module | CC1101 (868 MHz ISM, EU) |

### RF module — GERUI CC1101 868 MHz

A dedicated CC1101 breakout board with integrated antenna. The GERUI board labels its SPI data pins `SI` (MOSI) and `SO` (MISO).

### Wiring — GERUI CC1101 → ESP32-WROOM-32

| GERUI CC1101 pin | ESP32 GPIO | Board label |
|---|---|---|
| VCC | 3.3 V | 3V3 |
| GND | GND | GND |
| SCK | GPIO 18 | 18 / SCK |
| SI (MOSI) | GPIO 23 | 23 / MOSI |
| SO (MISO) | GPIO 19 | 19 / MISO |
| CS (CSN) | GPIO 5 | 5 / SS |
| GDO0 | GPIO 4 | 4 |
| GDO2 | — | not connected |

> **Important:** GPIO 6–11 are reserved for internal flash on the WROOM-32 and must not be used.

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
  "rain_rate_mmh": 0.6,
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
| `rain_rate_mmh` | mm/h | Derived every 60s from the accumulation delta |
| `battery_low` | boolean | True when transmitter battery is low |

---

## Manual Daily Rain Correction

The receiver accumulates its own daily rain total from the raw RF tip counter, persisted across reboots. If it ever drifts from the console's own reading (e.g. a reflash that landed between tips), correct it by publishing to a fixed MQTT control topic — see the `mqtt: on_message:` block in `davis-vantage-receiver.yaml`:

```bash
mosquitto_pub -h <broker> -t weatherdatalogger/davis-vantage-receiver/set_daily_rain -m "5.4"
```

Or on the server, using the shared config for broker/credentials (installed by `deploy.sh` alongside its own script):

```bash
/opt/weatherdatalogger/scripts/set_daily_rain.sh 5.4
```

By default it reads `/opt/weatherdatalogger/config.ini`; override with `CONFIG_INI=/path/to/config.ini`. The value is clamped to `< 500mm` on-device (implausible values are logged and ignored, not applied).

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
| Davis Wind Direction | Sensor | ° |
| Davis Wind Cardinal | Text sensor | e.g. `WSW` |
| Davis Daily Rain | Sensor | mm |
| Davis Rain Rate | Sensor | mm/h |
| Davis Battery Low | Binary sensor | on/off |
| Davis RSSI | Sensor (diagnostic) | dBm |
| Davis LQI | Sensor (diagnostic) | — |

Wind speed is smoothed with a 5-sample sliding window average. Wind direction is exposed both as a numeric degrees sensor (`device_class: wind_direction`) and as a separate 16-point compass text sensor. Rain rate is derived every 60 s from the change in accumulated rainfall.
