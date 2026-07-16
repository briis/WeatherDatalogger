# Davis Vantage Vue — ESPHome RF Receiver

Receives 868 MHz ISM band transmissions from a **Davis Vantage Vue** weather station and publishes decoded observations to MQTT under the project's standard topic namespace.

> **Installation:** Follow the [server installation guide](../README.md#installation) first. The ESPHome firmware is flashed independently — see [Setup](#setup) below.

> **Hardware revision (2026-07-16):** the receiver was rebuilt on an **M5Stack Basic Core** (`davisnet-weatherlogger.yaml`) — a sturdier, case-enclosed build with a built-in color display and an external-antenna CC1101 module for better range. RF decoding, MQTT topics, and all published fields are unchanged from the original breadboard build — see [Field conventions](#field-conventions). The original ESP32-WROOM-32 + breakout-board build (`davis-vantage-receiver.yaml`) is superseded; this README now documents the M5Stack build only. See git history for the old wiring if you still have one of those units deployed.

---

## Hardware

### Receiver board — M5Stack Basic Core (ESP32)

| Spec | Value |
|---|---|
| SoC | ESP32 (Xtensa LX6 dual-core) |
| Flash | 16 MB |
| PSRAM | None |
| Built-in display | 2" MIPI SPI LCD (`M5CORE` model — see [Display](#display--built-in-m5stack-core-lcd)) |
| Built-in buttons | 3× physical (A / B / C) |
| Built-in speaker | PWM-driven, GPIO 25 |
| Power management | IP5306 (I2C, `0x75`) — battery charging status only, polled every 30 s |
| RF module | CC1101, external antenna (see below) |
| Indoor sensor | BME280 (I2C, barometer/temp/humidity) |

`esphome:`/`esp32:` board id: `m5stack-core-esp32-16M`, `esp-idf` framework (the original build used `arduino`).

### RF module — M5Stack CC1101 Module (E07-900M10S / EBYTE, external antenna)

Stacks onto the Core via M5Stack's M-Bus connector — no manual SPI wiring. SCK/MISO/MOSI are the M-Bus's fixed SPI pins; CSN and GDO0 are selected via two onboard DIP-switch blocks. The external antenna (vs. the GERUI board's integrated antenna on the previous build) gives noticeably better range.

| Function | Pin | How it's selected |
|---|---|---|
| SCK | GPIO 18 | Fixed (M-Bus) |
| MOSI | GPIO 23 | Fixed (M-Bus) |
| MISO | GPIO 19 | Fixed (M-Bus) |
| CS (CSN) | GPIO 15 | DIP switch — **CSN block** (top, 4 switches): #2 ON, all others OFF |
| GDO0 | GPIO 35 | DIP switch — **GDO block** (bottom, 6 switches): #4 ON, all others OFF |
| GDO2 | — | Not connected — not required for Davis packet reception |

> The DIP-switch mapping above is specific to stacking on a "Core" host (M5Stack's module supports several host boards, each with a different pin mapping). Reception confirmed via CRC-validated Davis packets (packet types 3, 5, 8, 10, 14, correct `unit_id`) on 2026-07-16.

### Indoor sensor — BME280 (barometer / indoor temperature / indoor humidity)

A BME280 breakout wired to the Core's I2C bus (Grove Port A), co-located with the receiver itself — not part of the outdoor ISS. Provides a barometer reading plus indoor temperature/humidity for wherever the receiver is installed. Shares the bus with the Core's onboard IP5306 (`0x75`) — no address conflict.

| BME280 pin | ESP32 GPIO | Board label |
|---|---|---|
| VCC | 3.3 V | 3V3 |
| GND | GND | GND |
| SCL | GPIO 22 | 22 (Grove Port A) |
| SDA | GPIO 21 | 21 (Grove Port A) |

Address `0x76` (update the `address:` key in the yaml if a different breakout ties SDO to 3.3V for `0x77` instead).

### Display — built-in M5Stack Core LCD

The Core's built-in 2" color LCD (`display: platform: mipi_spi`, `model: M5CORE`) replaces the previous build's separate I2C OLED — no extra wiring, it's part of the module. `cs_pin: 14`, `dc_pin: 27`, `reset_pin: 33`; backlight is a switchable GPIO (`pin: 32`, exposed as a "Backlight" switch, defaults `ALWAYS_ON`).

Unlike the old OLED's time-based auto-cycle, paging is now **button-driven**, using the Core's 3 physical buttons:

| Button | GPIO | Action |
|---|---|---|
| A (left) | 39 | Previous page (wraps) |
| B (center) | 38 | Toggle backlight |
| C (right) | 37 | Next page (wraps) |

Every page shares the same header — synced clock, title, and a WiFi-connectivity icon:

1. **Date & time** — synced clock, date, and the device's IP address
2. **Temperature / Humidity** — temperature/humidity, feels-like, dew point, indoor temp/humidity
3. **Wind** — wind speed/cardinal, gust, lull, Beaufort description
4. **Rain** — daily rain total and rain rate
5. **Pressure** — sea-level pressure, its trend, and station pressure

> See the `display: platform: mipi_spi` lambda in `davisnet-weatherlogger.yaml` to change what's shown.

### Davis Vantage Vue

- 868 MHz ISM band wireless sensor suite (EU frequency plan)
- Protocol is community-reverse-engineered (not officially documented)
- Transmits wind on every packet; temperature, humidity, UV, solar, and rain each arrive in their own packet type (~every 20-30 s per measurement). This particular ISS has no UV or solar sensor fitted, and — confirmed by a 40-minute on-device packet-type histogram — never sends its own dedicated gust broadcast (packet type 9) at all, so gust and lull are both derived locally instead (see [How it works](#how-it-works))

---

## RF Configuration

| Parameter | Value | Notes |
|---|---|---|
| Frequency | 868.35 MHz | Empirically recentred; see comments in the YAML for the freq_offset data behind it |
| Modulation | GFSK | |
| Symbol rate | 19 200 baud | |
| FSK deviation | 9.5 kHz | |
| Filter BW | 650 kHz | Narrowed from an original 325 kHz — this transmitter doesn't hop, so a tighter filter cuts admitted noise without losing signal |
| Packet length | 8 bytes | Fixed |
| Sync word | `0xCB89` | 16/16 mode |
| CRC | Off | CRC-16/CCITT verified in firmware with bit-shift fallback |

---

## How it works

1. **Packet reception** — CC1101 receives raw 8-byte frames on 868.35 MHz
2. **Bit reversal** — bytes are LSB→MSB reversed to match Davis bit order
3. **CRC validation** — CRC-16/CCITT checked with up to 3 bit-shift attempts to handle alignment
4. **Station lock** — the first valid station ID seen is auto-locked; packets from other stations are silently ignored. Override by setting `known_unit_id` to a specific value (0 = Davis transmitter ID 1, 1 = ID 2, etc.)
5. **Decoding** — packet type byte selects the measurement: wind (every packet), temperature (type 8), UV (type 3, no sensor fitted here), solar radiation (type 5, no sensor fitted — publishing disabled entirely since RF noise made the "no sensor" sentinel unreliable), humidity (type 10), rain (type 14, but see below). Packet type 9 (Davis' own gust broadcast) is decoded if it's ever observed, but this specific transmitter has never been seen sending it
6. **Gust and lull** — derived locally every 60 s as the rolling max/min of the ordinary wind samples present in every packet (the same way the console's own display evidently does it), since dedicated gust packets don't arrive on this hardware
7. **Beaufort scale** — derived on every packet from `Wind Speed`'s own smoothed 5-sample moving average (not gusts), the closest available stand-in on this hardware for the WMO's 10-min sustained-mean convention. Bucketed 0-12 per the standard Beaufort thresholds; the accompanying description (e.g. `Fresh breeze`) is localized per the `language` substitution — see [Localization](#localization)
8. **Rain** — `Daily Rain`/`Rain Rate` are computed standalone from the ISS's own RF tip counter (packet type 14, 0.2 mm/tip), the same way the Davis console itself derives rain — no external station required. Rate is derived from the actual gap between tips (not a fixed 60s bucket), and decays back to 0 if no tip has been seen for 5+ minutes. [Manual/Meteobridge correction](#manual--automated-rain-corrections) is available as an optional override but nothing here depends on it
9. **Indoor sensor** — the BME280 is polled locally every 60s over I2C (not part of RF decoding at all) and published alongside everything else in `observation`
10. **Sea-level pressure & trend** — sea-level pressure is recomputed on-device every time the BME280 reports a new station pressure (every 60s), using the same barometric formula as `tempest_datalogger.py`, so it tracks station pressure without lag. The `elevation_m`/`height_above_ground_m` substitutions at the top of the yaml feed the conversion — adjust them for your install. The trend (±1 mb Rising/Falling threshold, also matching `tempest_datalogger.py`) is sampled separately every 15 min and needs 3h of on-device history (12 samples, 15 min apart, tracked with no wall-clock dependency — see the `pressure_hist_*` globals). The history buffer is flash-persisted (`restore_value: yes`), so it's only unavailable for ~3h15m after the very first boot or a full erase-reflash, not after every routine reboot/OTA update. The trend description (`Rising`/`Steady`/`Falling`) is localized per the `language` substitution, same as Beaufort
11. **Wet bulb, delta T, air density** — computed on-device alongside the other comfort metrics (step 7 above), same formulas as `tempest_datalogger.py`. Wet bulb uses a 50-iteration bisection solver and, like sea-level pressure, needs the BME280's station pressure — so it's only computed once a barometer reading is available
12. **Publishing** — consolidated `observation` payload published on every packet using the latest known values for all fields
13. **Local display** — the built-in LCD (see [Display](#display--built-in-m5stack-core-lcd)) redraws every 1s and shows 5 pages (Date/Time, Temp/Humidity, Wind, Rain, Pressure), switched with the physical A/C buttons rather than auto-cycling, independent of MQTT/RF timing

### Localization

The `language` substitution at the top of `davisnet-weatherlogger.yaml` controls the language of three derived text fields: the Beaufort description (`wind_beaufort_description`), the pressure trend descriptions (`pressure_trend`/`sea_level_pressure_trend`), and the 16-point Wind Cardinal (e.g. `WSW` → `VSV` in Danish, using Ø/Nord/Syd/Vest compass points). Supported values: `"en"` (English, default) and `"da"` (Danish). The underlying numeric values (`wind_beaufort`, `pressure_trend_mb`, `wind_direction_deg`, etc.) are unaffected — only the human-readable text changes. To add another language, extend the lookup tables in the packet lambda (Beaufort, Wind Cardinal) and the 15-min interval lambda (pressure trend).

---

## MQTT Topics

All topics are under `weatherdatalogger/davis-<id>/` where `<id>` is the locked station unit ID (0–7).

| Topic | Frequency | Content |
|---|---|---|
| `.../observation` | Every packet (~2.5 s) | All latest known values — flat JSON |
| `.../rapid_wind` | Every packet | `wind_avg_ms`, `wind_direction_deg` |
| `.../device_status` | Every packet | `rssi`, `lqi`, `battery_low` |

The one exception is the daily rain correction control topic (`weatherdatalogger/davisnet-datalogger/set_daily_rain`), which uses the device's static name instead of the dynamic `davis-<id>` prefix, since the transmitter ID auto-locks at runtime and isn't known ahead of time — see [Manual Daily Rain Correction](#manual-daily-rain-correction).

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
  "wind_lull_ms": 1.8,
  "wind_beaufort": 2,
  "wind_beaufort_description": "Light breeze",
  "dew_point_c": 12.9,
  "vapor_pressure_mb": 14.9,
  "heat_index_c": 18.2,
  "wind_chill_c": 18.2,
  "feels_like_c": 18.2,
  "station_pressure_mb": 1013.2,
  "indoor_temperature_c": 21.4,
  "indoor_humidity_pct": 45.0,
  "sea_level_pressure_mb": 1023.6,
  "pressure_trend_mb": -1.4,
  "pressure_trend": "Falling",
  "sea_level_pressure_trend_mb": -1.4,
  "sea_level_pressure_trend": "Falling",
  "wet_bulb_c": 14.1,
  "delta_t_c": 4.1,
  "air_density_kgm3": 1.223,
  "battery_low": false
}
```

`uv_index` and `solar_radiation_wm2` are defined in the payload builder but will essentially never appear on this receiver — no UV or solar sensor is fitted, and solar publishing is disabled entirely on top of that (see [Field conventions](#field-conventions)). Any field not yet received since last boot is omitted until the relevant packet type arrives. The DB writer treats missing fields as SQL NULL.

### Field conventions

All field names follow the project standard — descriptive snake_case with SI unit suffix:

| Field | Unit | Notes |
|---|---|---|
| `wind_avg_ms` | m/s | 5-packet moving average applied by ESPHome |
| `wind_gust_ms` | m/s | Locally-derived rolling max of `wind_avg_ms` over each 60s interval — packet type 9 (Davis' own gust broadcast) has never been observed on this hardware. Still updates immediately if a real ptype-9 packet ever arrives |
| `wind_lull_ms` | m/s | Locally-derived rolling min of `wind_avg_ms` over each 60s interval |
| `wind_direction_deg` | ° | 0–360 |
| `wind_beaufort` | Beaufort force (0-12) | Derived every packet from `wind_avg_ms`'s smoothed moving average (not gusts) — see [How it works](#how-it-works) |
| `wind_beaufort_description` | — | e.g. `Fresh breeze` — localized per the `language` substitution ([Localization](#localization)) |
| `air_temperature_c` | °C | |
| `relative_humidity_pct` | % | |
| `dew_point_c`, `vapor_pressure_mb`, `heat_index_c`, `wind_chill_c`, `feels_like_c` | °C / hPa | Comfort metrics computed on-device from temperature/humidity/wind — same formulas as `tempest_datalogger.py` |
| `rain_accumulation_mm` | mm | Today's accumulated rain, computed standalone from the ISS's own RF tip counter (see [How it works](#how-it-works)). Persisted across reboots, reset at local midnight |
| `rain_rate_mmh` | mm/h | Current rain rate, derived from the actual gap between tips. Decays to `0` after 5+ minutes without a tip |
| `uv_index` | UV Index | Packet type 3 decoded, but this ISS has no UV sensor fitted — will essentially never populate |
| `solar_radiation_wm2` | W/m² | Not published — no solar sensor fitted, and RF noise made the "no sensor" sentinel unreliable enough that publishing was disabled entirely rather than risk showing a bogus value |
| `station_pressure_mb` | hPa/mb | From the BME280, polled locally over I2C — not RF-decoded. Named `_mb` (not `_hpa`) to match the DB writer's/Tempest's convention; hPa and mb are numerically identical |
| `indoor_temperature_c` | °C | BME280, co-located with the receiver — indoor/enclosure temperature, not outdoor air temperature |
| `indoor_humidity_pct` | % | BME280, co-located with the receiver |
| `sea_level_pressure_mb` | hPa/mb | Computed on-device from `station_pressure_mb` on every barometer update (every 60s) — same formula as `tempest_datalogger.py`, see [How it works](#how-it-works) |
| `pressure_trend_mb`, `pressure_trend`, `sea_level_pressure_trend_mb`, `sea_level_pressure_trend` | hPa/mb | Sampled from station/sea-level pressure every 15 min — same thresholds as `tempest_datalogger.py`, see [How it works](#how-it-works). Omitted from the payload for ~3h15m after the very first boot/erase-reflash, until enough on-device history accumulates (the history buffer itself is flash-persisted, so a routine reboot doesn't reset this wait) |
| `wet_bulb_c`, `delta_t_c`, `air_density_kgm3` | °C / kg/m³ | Computed on-device alongside the other comfort metrics — same formulas as `tempest_datalogger.py`. Needs both temp/humidity and `station_pressure_mb`, so it's omitted until a barometer reading is available |
| `battery_low` | boolean | True when transmitter battery is low |

---

## Manual & Automated Rain Corrections

`Daily Rain` and `Rain Rate` are computed standalone on-device from the ISS's own RF tip counter (packet type 14) — see [How it works](#how-it-works). No external station is required for normal operation.

The MQTT topics below remain available as an **optional** manual/automated correction — e.g. to punch in the console's displayed value after a reflash/reboot that landed between tips (losing sync with the physical tip counter), or as a periodic cross-check if you happen to have an independent source like a Meteobridge. Both are fixed control topics (not the dynamic `weatherdatalogger/davis-<id>` observation prefix, since the transmitter ID auto-locks at runtime and isn't known at compile time) — see the `mqtt: on_message:` block in `davisnet-weatherlogger.yaml`:

```bash
mosquitto_pub -h <broker> -t weatherdatalogger/davisnet-datalogger/set_daily_rain -m "5.4"
mosquitto_pub -h <broker> -t weatherdatalogger/davisnet-datalogger/set_rain_rate -m "2.3"
```

Or on the server, for the daily total, using the shared config for broker/credentials (installed by `deploy.sh` alongside its own script):

```bash
/opt/weatherdatalogger/scripts/set_daily_rain.sh 5.4
```

By default it reads `/opt/weatherdatalogger/config.ini`; override with `CONFIG_INI=/path/to/config.ini`. Both values are clamped to `< 500mm` (or mm/h) on-device — implausible values are logged and ignored, not applied.

**[`weatherdatalogger/meteobridge/`](../weatherdatalogger/meteobridge/)**, if you have one wired to the same Vantage Vue ISS, no longer pushes automated corrections into the two topics above — it's now a full station integration with its own database rows (`weatherdatalogger/meteobridge-<mac>/observation`) rather than a correction feed for this device. To compare its rain reading against this device's RF-tip-derived one, query the database directly (both are logged under their own `station_id`) rather than looking at these entities. See its README for setup.

---

## Setup

### 0. Set elevation (optional)

The `substitutions:` block at the top of `davisnet-weatherlogger.yaml` has `elevation_m`/`height_above_ground_m`, used only for the Sea Level Pressure conversion. Defaults to `0`/`0` (station pressure = sea level pressure) if left unset — fine for testing, but adjust to your actual install for a meaningful reading.

The same block also has `language` (`"en"` or `"da"`), controlling the Beaufort and pressure trend description text — see [Localization](#localization).

### 1. Set the CC1101 module's DIP switches

Before stacking the CC1101 module onto the Core, set its two DIP-switch blocks for a "Core" host — see the [RF module](#rf-module--m5stack-cc1101-module-e07-900m10s--ebyte-external-antenna) table above (CSN block #2 ON, GDO block #4 ON, all other switches OFF). Wrong switches show up as "CC1101 isn't receiving RF frames at all" — see [Debugging this file](../AGENT.md#debugging-this-file) in AGENT.md.

### 2. Create `secrets.yaml`

In the same directory as the YAML file (or your ESPHome config directory), create `secrets.yaml`:

```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "YourWiFiPassword"
fallback_ap_password: "YourFallbackAPPassword"
mqtt_broker: "192.168.1.10"
mqtt_username: "your_mqtt_user"
mqtt_password: "your_mqtt_password"
ota_password: "your_ota_password"
# api_encryption_key: "your_32_byte_base64_key"   # generate: openssl rand -base64 32
# only needed if you uncomment `api:` in the yaml — see below
```

> Like the previous build, `api:` (native API, used for remote `esphome logs`/OTA) is **commented out by default** — uncomment it (and provide `api_encryption_key` above) only if you need remote logs/OTA over the native API. If you do, see [Home Assistant Integration](#home-assistant-integration) below for why you should still avoid adding this node a second time via HA's "ESPHome" integration UI.

### 3. Flash the firmware

Install the ESPHome CLI if not already installed:

```bash
pip install esphome
```

Flash for the first time over USB:

```bash
esphome run davis/davisnet-weatherlogger.yaml
```

Subsequent updates can be flashed over Wi-Fi (OTA):

```bash
esphome run davis/davisnet-weatherlogger.yaml
```

### 4. Verify

Check ESPHome logs:

```bash
esphome logs davis/davisnet-weatherlogger.yaml
```

You should see `Auto-locked to station ID: X` on the first valid packet, then wind readings every ~2.5 s. Verify MQTT output:

```bash
mosquitto_sub -h <broker> -t "weatherdatalogger/davis-#" -v
```

---

## Home Assistant Integration

The ESPHome firmware connects to HA via **MQTT discovery** (`mqtt: discovery: true`), grouping all entities under one "Davisnet Datalogger" device — same as how the Tempest/AirLink Python services register their devices. The `api:` block in the YAML is commented out by default; it exists only for remote `esphome logs`/OTA over the native API if you choose to enable it. If you do, **do not** also add this node through Home Assistant's "ESPHome" integration UI, or entities would be duplicated (once via native API, once via MQTT discovery).

Entity names no longer repeat "Davis" (the device name already provides that context) — HA shows the short name on the device's own page and the full "Davisnet Datalogger <name>" combination in out-of-context views like the global entity picker:

| Entity | Type | Unit | Notes |
|---|---|---|---|
| Temperature | Sensor | °C | |
| Humidity | Sensor | % | |
| Wind Speed | Sensor | m/s | 5-sample sliding window average |
| Wind Gust | Sensor | m/s | Locally-derived (see [How it works](#how-it-works)) |
| Wind Lull | Sensor | m/s | Locally-derived |
| Wind Direction | Sensor | ° | |
| Wind Cardinal | Text sensor | e.g. `WSW` | 16-point compass, derived from Wind Direction — localized per the `language` substitution ([Localization](#localization)) |
| Beaufort Scale | Sensor | Beaufort force (0-12) | Derived from Wind Speed's smoothed average, not gusts (see [How it works](#how-it-works)) |
| Beaufort Description | Text sensor | e.g. `Fresh breeze` | Localized per the `language` substitution ([Localization](#localization)) |
| Dew Point | Sensor | °C | |
| Vapor Pressure | Sensor | hPa | |
| Heat Index | Sensor | °C | |
| Wind Chill | Sensor | °C | |
| Feels Like | Sensor | °C | |
| Wet Bulb Temperature | Sensor | °C | 50-iteration bisection solver; needs a barometer reading, unavailable until one arrives |
| Delta T | Sensor | °C | Air temperature minus Wet Bulb Temperature |
| Air Density | Sensor | kg/m³ | |
| UV Index | Sensor | UV Index | No sensor fitted — will essentially never show a value |
| Solar Radiation | Sensor | W/m² | No sensor fitted, publishing disabled — always "Unavailable" by design, not a fault |
| Daily Rain | Sensor | mm | Persists across reboots; resets at local midnight |
| Rain Rate | Sensor | mm/h | Decays to 0 after 5 min without a tip |
| Barometer | Sensor | hPa | BME280, local to the receiver — not RF-decoded |
| Sea Level Pressure | Sensor | hPa | Computed on-device from Barometer + `elevation_m`/`height_above_ground_m` |
| Pressure Trend | Sensor | hPa | 3h delta of Barometer; unavailable for ~3h15m after the very first boot/erase-reflash (flash-persisted afterward, so routine reboots don't reset the wait) |
| Sea Level Pressure Trend | Sensor | hPa | 3h delta of Sea Level Pressure |
| Pressure Trend Description | Text sensor | e.g. `Falling` | ±1 hPa Rising/Falling threshold, else `Steady` — localized per the `language` substitution ([Localization](#localization)) |
| Sea Level Pressure Trend Description | Text sensor | e.g. `Falling` | Same thresholding, for Sea Level Pressure |
| Indoor Temperature | Sensor | °C | BME280, local to the receiver |
| Indoor Humidity | Sensor | % | BME280, local to the receiver |
| Battery Low | Binary sensor | on/off | Davis transmitter battery, not the M5Stack's own power |
| Charging | Binary sensor | on/off | M5Stack Core's onboard IP5306, polled over I2C every 30s — reflects USB power connected, not a fuel gauge |
| Backlight | Switch | on/off | Built-in LCD backlight; also toggled by the physical B button — defaults `ALWAYS_ON` |
| Speaker Test Beep | Button | — | Plays a short beep on the Core's onboard speaker (PWM/`rtttl:`), useful to confirm the module is alive |
| RSSI | Sensor (diagnostic) | dBm | |
| LQI | Sensor (diagnostic) | — | |
| Restart | Button (diagnostic) | — | Also available on the local web UI (`http://<device-ip>/`, port 80) |
