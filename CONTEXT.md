# WeatherDatalogger — Project Context

## Goal

A unified weather data pipeline that collects data from **multiple weather station brands** and publishes everything to a single MQTT broker under a common topic namespace. Downstream consumers (Home Assistant, databases, dashboards, etc.) subscribe to MQTT and are completely decoupled from the hardware. A separate DB writer service subscribes to MQTT and persists readings to MariaDB for historical analysis and dashboarding.

---

## MQTT Topic Structure

```
weatherdatalogger/
  tempest-<serial>/        ← WeatherFlow Tempest (Python service)
    observation            — full obs_st payload (raw + derived metrics)
    rapid_wind
    rain_start
    lightning
    device_status
    hub_status
  forecast-<location>/     ← WeatherFlow Better Forecast REST API (optional)
    current                — current conditions JSON object
    forecast_hourly        — hourly forecast JSON array (up to forecast_hours entries)
    forecast_daily         — 10-day daily forecast JSON array
  davis-<id>/              ← Davis Vantage Vue (ESPHome firmware, active)
    observation            — flat JSON: wind, temp, rain(+rate), derived
                              comfort metrics; relative_humidity_pct is
                              relayed from the AirLink over MQTT, NOT from
                              this station's own RF link (see Known Issues)
    rapid_wind
    device_status
  airlink-<did>/           ← Davis AirLink air quality sensor (Python service)
    observation            — PM1/PM2.5/PM10, AQI, temperature, humidity
```

`<serial>` for Tempest comes from the hub's UDP broadcast (`ST-…` for the sensor, `HB-…` for the hub).
`<id>` for Davis is the station ID locked by the CC1101 receiver.

All payloads are **flat JSON objects** with human-readable field names and SI units where applicable.

---

## Hardware Overview

### WeatherFlow Tempest
- All-in-one wireless weather station
- The **Tempest Hub** broadcasts UDP packets on **port 50222** (LAN broadcast)
- No additional receiver hardware needed — the hub does it all
- Protocol documented at: https://apidocs.tempestwx.com/reference/tempest-udp-broadcast

### Davis Vantage Vue
- 868 MHz ISM band wireless sensor suite (EU frequency plan)
- Protocol is community-reverse-engineered (not officially documented)
- Receiver: **ESP32-WROOM-32** (30-pin devkit) + **GERUI CC1101** — recentred to
  868.3206MHz / 102kHz filter (empirically derived; see Known Issues), CRC-16/CCITT
- Runs **ESPHome** firmware (`davis/davis-vantage-receiver.yaml`) which handles RF decoding and MQTT publishing
- HA entities come from ESPHome's own MQTT discovery (`mqtt: discovery: true`), grouped
  under one "Davis Vantage Receiver" device — same visual result as Tempest/AirLink's
  hand-rolled discovery, just via ESPHome's built-in mechanism instead
- `api:` is kept solely for remote `esphome logs`/OTA — this node must NOT also be
  added via Home Assistant's "ESPHome" integration UI, or entities would duplicate
- **Status: active and field-tested — temperature/wind/rain/humidity reliable; gust
  not receivable over RF on this hardware, see Known Issues**

### Davis AirLink
- Air quality sensor measuring PM1.0, PM2.5, and PM10 particulate matter
- Provides 2-min averages plus 1h/3h/24h averages and EPA NowCast values
- Local HTTP REST API at `http://<host>/v1/current_conditions` (no authentication required)
- `airlink_datalogger.py` polls the API every 60 s (configurable) and publishes to MQTT
- Temperature and humidity readings are included (device internal sensors, used for PM correction)
- AQI (US EPA) is computed from NowCast concentration before publishing
- **Status: active**

---

## Known Issues

### Davis Vantage Vue never receives RF gust packets

The Vantage Vue ISS transmits wind + temperature + rain reliably, but **packet
type 9 (wind gust) never occurs on this hardware** — confirmed by a 40-minute
on-device packet-type histogram capture (every one of the 16 possible 4-bit
packet types was tallied continuously; only types 3, 5, 8, 14 ever appeared,
with zero occurrences of 9). Packet type 10 (humidity) was also missing under
the original 102kHz `filter_bandwidth`, but widening it to 650kHz resolved
that — humidity is now received directly over RF and no MQTT-relayed fallback
is needed. Gust investigation before concluding it's not fixable in software:

- **Not a frequency-hop problem** — `freq_offset` telemetry showed every packet
  type arriving on the exact same frequency; this transmitter does not hop.
- **Not a decode-formula bug** — packet type 3 (received often, at the same
  cadence as temperature) was checked and ruled out as a disguised gust
  reading — its payload bytes don't track a plausible gust value.
- The physical console *does* show correct, live gust, proving the ISS can
  produce it somehow — just not via whatever this specific CC1101 module and
  its passive-listening approach can capture.

**Not abandoned** — a different-brand CC1101 module has been ordered to test
whether this is module-specific. The on-device packet-type histogram/`CAL`
logging used to diagnose this is still in the yaml, commented out for quick
re-enabling (search `CALIBRATION (disabled)` in `davis-vantage-receiver.yaml`).
See the "What's next / TODO" list in AGENT.md.

### MQTT `reboot_timeout` can mask its own diagnostics

`mqtt: reboot_timeout: 15s` (ESPHome) forces a full device reboot if the MQTT
connection stays down longer than the timeout. This silently reset in-memory
diagnostic counters (globals) before they could accumulate — the symptom
looked like "the data never gets created," when actually the device was
rebooting every 10-25 minutes on routine MQTT hiccups. Fixed by setting
`reboot_timeout: 0s` (disabled) on the Davis receiver. Worth checking on any
other ESPHome node using aggressive `reboot_timeout` values combined with a
flaky broker connection, and worth remembering generally: repeating
`[I][safe_mode:142]: Boot seems successful` log lines are the tell that a
device has been reboot-looping, even when nothing else in the log obviously
says so.

---

## Repository Structure

```
WeatherDatalogger/                   ← repo root
├── weatherdatalogger/               ← mirrors /opt/weatherdatalogger/ on the LXC
│   ├── tempest/                     ← WeatherFlow Tempest service
│   │   ├── tempest_datalogger.py   ← Main Python service (UDP → MQTT, single file)
│   │   ├── config.dev.ini          ← Dev container config (local mosquitto)
│   │   ├── requirements.txt        ← Runtime dependency: paho-mqtt
│   │   ├── scripts/
│   │   │   └── simulate_udp.py    ← Sends all 6 Tempest message types to localhost
│   │   ├── systemd/
│   │   │   └── tempest-datalogger.service
│   │   └── README.md
│   ├── airlink/                     ← Davis AirLink air quality service
│   │   ├── airlink_datalogger.py   ← Main Python service (HTTP polling → MQTT, single file)
│   │   ├── requirements.txt        ← Runtime dependency: paho-mqtt
│   │   ├── systemd/
│   │   │   └── airlink-datalogger.service
│   │   └── README.md
│   ├── database/                    ← MariaDB persistence layer
│   │   ├── db_writer.py            ← MQTT → MariaDB writer service (single file)
│   │   ├── requirements.txt        ← Runtime deps: paho-mqtt, PyMySQL
│   │   ├── 01_create_database.sql  ← One-time: create DB + user
│   │   ├── 02_create_tables.sql    ← One-time: create all tables
│   │   ├── migrations/             ← Numbered ALTER TABLE scripts (applied by deploy)
│   │   ├── systemd/
│   │   │   └── weatherdb-writer.service
│   │   └── README.md
│   ├── scripts/
│   │   └── deploy.sh               ← Pull from GitHub, install all services, run migrations
│   └── config.example.ini          ← Shared config template for all three services
├── davis/                           ← Davis Vantage Vue (ESPHome receiver — not deployed to LXC)
│   ├── davis-vantage-receiver.yaml ← ESPHome firmware (CC1101 RF → MQTT)
│   └── README.md
├── scripts/
│   └── lint                        ← ruff format + ruff check --fix (dev only)
├── requirements-dev.txt             ← Shared dev/lint tools: ruff
├── .ruff.toml                       ← Ruff linter config (target-version = "py311")
├── README.md                        ← Server installation guide + project overview
├── CONTEXT.md                       ← This file
└── AGENT.md                         ← Instructions for AI coding assistants
```

---

## Deployment Environment

- **Proxmox** hypervisor running **Debian Bookworm LXC containers**
- Production Python: **3.13** (the system `python3` on the LXC)
- All services installed under `/opt/weatherdatalogger/` as the `tempest` unprivileged user:
  - `tempest-datalogger` — files at `/opt/weatherdatalogger/tempest/`, venv at `.../tempest/venv`
  - `airlink-datalogger` — files at `/opt/weatherdatalogger/airlink/`, venv at `.../airlink/venv`
  - `weatherdb-writer` — files at `/opt/weatherdatalogger/database/`, venv at `.../database/venv`
- **Single shared config** at `/opt/weatherdatalogger/config.ini` — all three services read from this one file; never overwritten by the deploy script
- **MariaDB** running on the same LXC, bound to `0.0.0.0:3306` for network access
  - `db.cnf` (MySQL client format, `chmod 600`) auto-generated at `/opt/weatherdatalogger/db.cnf` by the deploy script from the shared `config.ini`
- Deploy script: `sudo bash /opt/weatherdatalogger/scripts/deploy.sh`
  - Installs all production files for all services
  - Applies pending SQL migrations from `database/migrations/`
  - Updates Python dependencies in each venv
  - Restarts each service if it was already enabled (skips on first deploy before config is set)
- The LXC must be on the **same L2 network segment** as the Tempest Hub (UDP broadcast does not cross routed boundaries)

---

## Tempest Datalogger — Key Design Decisions

- Pure Python, **single file** (`tempest_datalogger.py`), no frameworks
- Only external dependency: `paho-mqtt`
- Config via INI file, path passed with `--config`
- UDP socket binds `0.0.0.0:50222`, receives all hub broadcasts
- Auto-reconnects to MQTT on disconnect (`loop_start()` background thread)
- Each UDP message type maps to its own MQTT subtopic
- Payload fields use descriptive names with unit suffixes (`_ms`, `_mb`, `_c`, `_pct`, etc.)
- `obs_st` payloads include **derived metrics** computed in-process before publishing
- Database writes are deliberately NOT in this service — MQTT is the only output

---

## DB Writer — Key Design Decisions

- Pure Python, **single file** (`db_writer.py`), no frameworks
- External dependencies: `paho-mqtt`, `PyMySQL`
- Subscribes to `{base_topic}/+/observation` — wildcard covers all current and future station types
- Stations are **auto-registered** in the `stations` table on first observation
- `realtime` table: one row per station, upserted on every message (`INSERT … ON DUPLICATE KEY UPDATE`)
- `history` table: full append-only time-series, never updated
- All timestamps stored in **UTC** — `datetime.fromtimestamp(ts, tz=UTC).replace(tzinfo=None)`; always use `UTC_TIMESTAMP()` (not `NOW()`) when querying from MariaDB if the server timezone is not UTC
- Reconnects to MariaDB automatically on `OperationalError` (failed new connection) **and** `InterfaceError` (silently dropped existing connection, e.g. after a server restart); both error types are caught in `_execute()`
- Station type is derived from the MQTT topic segment (`tempest-ST-xxxx` → `tempest`)
- Config via INI file (`[mqtt]` + `[database]` + `[logging]`)

---

## Database Schema

Tables live in the `weatherdatalogger` database. All observation columns are shared between `realtime` and `history`. The complete schema is defined in `02_create_tables.sql`; migrations add incremental changes and must use `ADD COLUMN IF NOT EXISTS` for idempotency.

| Table / View | Purpose |
|---|---|
| `stations` | One row per device; auto-inserted on first observation |
| `realtime` | Latest reading per station (PK = `station_id`) |
| `history` | Full time-series; indexed on `(station_id, recorded_at)` |
| `history_charting` | Pre-aggregated 10-min combined windows (one row per UTC `window_start`); populated by `evt_aggregate_history_charting` event |
| `combined_realtime` | View merging latest Tempest (weather) + AirLink (air quality) into one row; use this for dashboards |
| `schema_migrations` | Tracks applied migration filenames |

### `history_charting` event

`evt_aggregate_history_charting` runs every 10 minutes via the MariaDB event scheduler. It looks back 30 minutes and uses `INSERT IGNORE` on the unique `window_start` key so re-runs are safe. All window boundaries use `UTC_TIMESTAMP()` and pure datetime arithmetic — never `NOW()` or `FROM_UNIXTIME` — because `recorded_at` is stored in UTC and the server may run in a different timezone.

The event scheduler must be enabled on the server:

```bash
echo -e "[mysqld]\nevent_scheduler = ON" | sudo tee /etc/mysql/mariadb.conf.d/99-local.cnf
sudo systemctl restart mariadb
```

Migrations are SQL files in `database/migrations/` named `YYYYMMDD_description.sql`. The deploy script applies any file not yet recorded in `schema_migrations`.

---

## Config Sections

All three services read from a single shared `config.ini`. The template with all documented keys is `config.example.ini` at the repo root (deployed to `/opt/weatherdatalogger/config.example.ini`).

Each service uses only the sections relevant to it — extra sections are ignored by `configparser`.

### Shared sections (all services)

| Section | Key settings |
|---|---|
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `retain`, `qos` |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` |

> **Note:** `client_id` is NOT in the shared config — each service's `DEFAULT_CONFIG` provides its own unique default (`tempest-datalogger`, `airlink-datalogger`, `weatherdb-writer`).

### tempest_datalogger.py

| Section | Key settings |
|---|---|
| `[udp]` | `listen_address`, `listen_port` |
| `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |
| `[forecast]` | `enabled`, `station_id`, `api_key`, `location`, `interval_min`, `forecast_hours` (default 48) |

`data_dir` (default: `/opt/weatherdatalogger/tempest`) controls where the persistence files are written:
- `tempest_lightning.json` — rolling 24h lightning event log
- `tempest_pressure.json` — rolling 24h pressure history for trend calculation

### airlink_datalogger.py

| Section | Key settings |
|---|---|
| `[airlink]` | `host` (**REQUIRED**), `port` (80), `interval_s` (60), `timeout_s` (10) |

### db_writer.py

| Section | Key settings |
|---|---|
| `[database]` | `host`, `port`, `name`, `user`, `password` (**REQUIRED**) |

---

## UDP Message Types (Tempest)

| Type            | MQTT subtopic    | Key fields                                                        |
|-----------------|------------------|-------------------------------------------------------------------|
| `obs_st`        | `observation`    | wind, pressure, temp, humidity, UV, solar, rain, lightning, battery + all derived metrics |
| `rapid_wind`    | `rapid_wind`     | wind speed + direction, every ~3 s                               |
| `evt_precip`    | `rain_start`     | timestamp only (event trigger)                                    |
| `evt_strike`    | `lightning`      | distance_km, energy                                               |
| `device_status` | `device_status`  | voltage, RSSI, sensor_status bitmask, uptime                     |
| `hub_status`    | `hub_status`     | firmware, uptime, radio_status, reset_flags                      |

---

## Derived Metrics (computed from obs_st, added to observation payload)

All derived fields follow the same unit-suffix convention as raw fields.

| Field | Description | Notes |
|---|---|---|
| `dew_point_c` | Dew point | Magnus formula |
| `wet_bulb_c` | Wet bulb temperature | Iterative bisection solver |
| `delta_t_c` | T_air − T_wet_bulb | Evaporation potential |
| `feels_like_c` | Apparent temperature | Heat index OR wind chill OR air temp |
| `heat_index_c` | Heat index | NWS Rothfusz; falls back to air temp below threshold |
| `wind_chill_c` | Wind chill | NWS formula; falls back to air temp above threshold |
| `vapor_pressure_mb` | Vapor pressure | |
| `air_density_kgm3` | Air density | |
| `rain_rate_mmh` | Rain rate | rain_accumulation_mm × 60 |
| `sea_level_pressure_mb` | Sea level pressure | Needs `elevation_m` + `height_above_ground_m` |
| `pressure_trend_mb` | Station pressure 3h delta | null until 3h history available; persisted across restarts |
| `pressure_trend` | "Rising" / "Steady" / "Falling" | ±1 mb threshold |
| `sea_level_pressure_trend_mb` | Sea level pressure 3h delta | same persistence |
| `sea_level_pressure_trend` | "Rising" / "Steady" / "Falling" | |
| `lightning_last_detected` | ISO 8601 UTC timestamp of last strike | null if none recorded; persisted |
| `lightning_count_3h` | Strike count in last 3 hours | persisted across restarts |
| `lightning_min_dist_3h_km` | Closest strike in 3h window | null if no strikes |
| `lightning_max_dist_3h_km` | Farthest strike in 3h window | null if no strikes |

---

## Home Assistant MQTT Discovery

When `[homeassistant] discovery = true`, the service publishes **retained** config messages to `homeassistant/sensor/<unique_id>/config` on first observation of each device. Home Assistant auto-creates:

- **Tempest ST-xxxxx** device — all raw + derived obs_st sensors
- **Tempest HB-xxxxx** device — hub status sensors
- **Forecast \<location\>** device — 9 sensors:
  - 7 current-condition sensors (condition, temperature, humidity, wind speed, wind bearing, sea level pressure, dew point) — `value_template` extracts each field from the `forecast-<location>/current` topic
  - 2 forecast-array sensors (Hourly Forecast, Daily Forecast) — state = entry count; `json_attributes_topic` + `json_attributes_template: "{{ {'forecasts': value_json} | tojson }}"` exposes the full array as the `forecasts` attribute

Discovery is published once per device per run (tracked with an in-memory set). The `lightning_last_detected` sensor uses `device_class: timestamp` so HA displays it natively as "2 hours ago".

> **Note:** HA MQTT integration does not support auto-discovery for `weather` entities (`homeassistant/weather/…` topics are silently ignored), and `mqtt: weather:` in `configuration.yaml` is also invalid. To create a full weather card with hourly/daily forecast, add a `template: weather:` block to `configuration.yaml` — the exact YAML is logged at INFO level the first time the forecast is published.

---

## Conventions

- Python: 3.13 on the production LXC; code written to be compatible with 3.11+ syntax (ruff target stays `py311`)
- Linting: ruff (`scripts/lint`), `select = ["ALL"]`, `target-version = "py311"`
- Logging: stdlib `logging`, level configurable in `config.ini`
- Config: `configparser` INI format
- Units: always SI in MQTT payloads; label field names with unit suffix
- MQTT QoS: default 0 (configurable), retain: default false (state topics), always true (HA discovery)
- Each service is a **single self-contained Python file** with its own `requirements.txt`
