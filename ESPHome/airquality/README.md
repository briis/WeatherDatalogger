# Air Quality Monitor (ESPHome)

An ESP32-C6 + SDS011 (PM2.5/PM10) + BME280 (temperature/humidity/pressure) build that publishes air-quality observations to MQTT under the project's standard `weatherdatalogger/` topic namespace, field-compatible with the Davis AirLink integration ([`weatherdatalogger/airlink/`](../../weatherdatalogger/airlink/)).

> **Installation:** Follow the [server installation guide](../../README.md#installation) first. The ESPHome firmware is flashed independently — see [Setup](#setup) below.

---

## Hardware

| Component | Notes |
|---|---|
| SoC | ESP32-C6 (`esp32-c6-devkitc-1`, esp-idf framework — Arduino-core support for C6 is newer/less mature) |
| PM sensor | Nova Fitness SDS011 — laser PM2.5/PM10, UART 9600 baud |
| Environmental sensor | BME280 — temperature/humidity/pressure, I2C |

### Wiring

| SDS011 | ESP32-C6 GPIO | Notes |
|---|---|---|
| TX | GPIO18 (`rx_pin`) | Sensor TX → ESP32 RX |
| RX | GPIO19 (`tx_pin`) | Sensor RX ← ESP32 TX (must be connected — `rx_only` is not set) |

| BME280 | ESP32-C6 GPIO | Notes |
|---|---|---|
| SDA | GPIO21 | |
| SCL | GPIO22 | Address `0x76` (change to `0x77` if a different breakout ties SDO high) |

---

## How it works

1. **PM measurement** — the SDS011 manages its own duty cycle: at the configured `update_interval` (5 min), it powers its laser/fan for ~30s, takes a reading, then powers down until the next cycle. This is a firmware setting persisted on the sensor itself, not something the ESP32 has to manage.
2. **Boot restore** — the last known PM2.5/PM10 readings are flash-persisted (`globals`, `restore_value: true`) and republished on boot, so AQI/CAQI don't sit blank for up to 5 minutes after a reboot while waiting for the first fresh SDS011 reading.
3. **BME280** — polled locally every 60s over I2C; publishes temperature, humidity, and pressure directly.
4. **Dew point** — computed on-device from BME280 temperature/humidity using the Magnus formula, the same one `ESPHome/davis/davisnet-weatherlogger.yaml` and `tempest_datalogger.py` use.
5. **AQI (US EPA)** — computed from the SDS011's **instantaneous** PM2.5/PM10 readings (not a 12-hour NowCast average like the Davis AirLink integration uses), via the EPA's May-2024-updated breakpoint table. This makes it an approximation that can swing more than an "official" NowCast-based AQI would — there's no on-device rolling-average buffer to smooth it. `AQI PM2.5`/`AQI PM10` publish the two sub-indices separately (matching AirLink's `aqi_pm2p5`/`aqi_pm10` DB columns — see [Field conventions](#field-conventions) for the caveat on why the numbers aren't bit-for-bit identical to AirLink's); `AQI` is the combined display sensor (`max` of the two, same EPA convention: air quality is only as good as the worst pollutant).
6. **CAQI (EU CITEAIR)** — computed from current concentration (not NowCast, by design — CAQI is a real-time hourly index), using the same breakpoint tables as `airlink_datalogger.py`. Extrapolated (capped at 200) beyond the official 0-100 band rather than omitted.
7. **Publishing** — a consolidated `observation` JSON is published every 60s using the latest known value of every field (PM/AQI/CAQI only actually change every 5 minutes due to the SDS011's duty cycle, but are republished every 60s alongside the BME280 readings so `realtime`/`history` in the database don't go stale between PM cycles).

---

## MQTT Topics

| Topic | Frequency | Content |
|---|---|---|
| `weatherdatalogger/aqmonitor-01/observation` | Every 60s | All latest known values — flat JSON |

`01` is the `device_id` substitution at the top of `air-quality-monitor.yaml` — bump it if a second unit is ever added to the same broker, so the two don't collide on the same topic/station_id.

### Example `observation` payload

```json
{
  "pm_2p5_ugm3": 6.3,
  "pm_10_ugm3": 9.8,
  "aqi_pm2p5": 26,
  "aqi_pm10": 9,
  "caqi_pm2p5": 10,
  "caqi_pm10": 10,
  "air_temperature_c": 18.4,
  "relative_humidity_pct": 61.2,
  "dew_point_c": 10.9,
  "station_pressure_mb": 1015.3
}
```

Any field not yet available since boot (e.g. PM/AQI/CAQI before the first SDS011 cycle completes) is omitted rather than sent as `null`. The DB writer treats missing fields as SQL NULL. `serial_number`/`timestamp` are deliberately not included — same convention as the Davis receiver — `db_writer.py` falls back to the topic segment (`aqmonitor-01`) and MQTT message-arrival time.

### Field conventions

| Field | Unit | Notes |
|---|---|---|
| `pm_2p5_ugm3`, `pm_10_ugm3` | µg/m³ | Instantaneous SDS011 reading, refreshed every 5 min |
| `aqi_pm2p5`, `aqi_pm10` | US EPA AQI (0-500) | Computed from the instantaneous reading using the May-2024-updated EPA breakpoint table — **not** the same breakpoint vintage `airlink_datalogger.py` uses, and not NowCast-smoothed like AirLink's. Same scale/definition, but values won't be bit-for-bit identical to an AirLink reading at the same concentration |
| `caqi_pm2p5`, `caqi_pm10` | EU CAQI (0-200, extrapolated beyond 100) | Same breakpoint tables and current-concentration convention as `airlink_datalogger.py` |
| `air_temperature_c`, `relative_humidity_pct` | °C / % | BME280 |
| `dew_point_c` | °C | Computed on-device, Magnus formula |
| `station_pressure_mb` | hPa/mb | BME280 — **not** published by the Davis AirLink (it has no barometer); included here since this hardware has one. Named `_mb` to match the DB writer's convention; hPa and mb are numerically identical |

There's no PM1.0, no 1h/3h/24h rolling averages, and no EPA NowCast on this hardware — the SDS011 only reports instantaneous PM2.5/PM10, unlike the AirLink's onboard averaging. Those `_OBS_FIELDS` columns (`pm_1_ugm3`, `pm_2p5_1h_ugm3`, `pm_2p5_nowcast_ugm3`, etc. — see `weatherdatalogger/database/db_writer.py`) simply stay `NULL` for this station.

---

## Home Assistant Integration

Unlike the Davis receiver (which uses ESPHome's own MQTT discovery), this device connects to Home Assistant via the **native ESPHome API** (`api:`) — add it through HA's "ESPHome" integration UI as usual. The `mqtt:` block exists solely to publish the `weatherdatalogger/aqmonitor-01/observation` topic for the database writer; it has `discovery: false` so entities aren't registered twice.

| Entity | Type | Unit | Notes |
|---|---|---|---|
| PM2.5, PM10 | Sensor | µg/m³ | Refreshes every 5 min (SDS011 duty cycle) |
| AQI | Sensor | AQI (0-500) | Combined display value — `max(AQI PM2.5, AQI PM10)` |
| AQI PM2.5, AQI PM10 | Sensor | AQI (0-500) | Per-pollutant sub-indices — published to MQTT as `aqi_pm2p5`/`aqi_pm10` |
| CAQI PM2.5, CAQI PM10 | Sensor | CAQI (0-200) | Published to MQTT as `caqi_pm2p5`/`caqi_pm10` |
| AQI Category | Text sensor | — | AQI category label (Good/Moderate/Unhealthy/…) |
| AQI Alarm | Binary sensor | on/off | `problem` device class, trips when AQI > 100 |
| Temperature, Humidity, Pressure | Sensor | °C / % / hPa | BME280 |
| Dew Point | Sensor | °C | Computed |
| Last Updated | Text sensor | — | Timestamp of the last real PM measurement |

---

## Feeding the `air_quality` role

`combined_realtime`'s `air_quality`-role columns (`pm_*`/`aqi_*`/`caqi_*`) default to sourcing from `station_type = 'airlink'` (see `station_roles` in [`database/README.md`](../../weatherdatalogger/database/)). This device registers as its own station (`station_type = 'aqmonitor'`, from the `aqmonitor-01` topic segment) — its readings land in `realtime`/`history` regardless, but won't appear in `combined_realtime` until the role points at it:

```sql
UPDATE station_roles SET station_type = 'aqmonitor' WHERE role = 'air_quality';
```

Both stations can stay registered side by side either way — reassigning the role only changes which one `combined_realtime`/`history_charting` read from; the losing station's own rows are still queryable directly by its `station_id`.

---

## Setup

### 1. Create `secrets.yaml`

In the same directory as the YAML file (or your ESPHome config directory):

```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "YourWiFiPassword"
fallback_ap_password: "YourFallbackAPPassword"
api_encryption_key: "your_32_byte_base64_key"   # generate: openssl rand -base64 32
ota_password: "your_ota_password"
mqtt_broker: "192.168.1.10"
mqtt_username: "your_mqtt_user"
mqtt_password: "your_mqtt_password"
```

### 2. Flash the firmware

```bash
pip install esphome
esphome run airquality/air-quality-monitor.yaml
```

Subsequent updates can be flashed over Wi-Fi (OTA) the same way.

### 3. Verify

```bash
esphome logs airquality/air-quality-monitor.yaml
mosquitto_sub -h <broker> -t "weatherdatalogger/aqmonitor-#" -v
```

You should see an `observation` message every 60s once the BME280 comes up; PM/AQI/CAQI fields appear once the first SDS011 cycle completes (up to 5 min after boot, or immediately if restored from flash on a warm reboot).
