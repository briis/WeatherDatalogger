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
  forecast-<location>/     ← Visual Crossing Weather API (Python service, optional, lat/lon-based)
    current                — current conditions JSON object
    forecast_hourly        — hourly forecast JSON array
    forecast_daily         — daily forecast JSON array (up to `days`, default/max 14)
  davis-<id>/              ← Davis Vantage Vue (ESPHome firmware, active)
    observation            — flat JSON: wind (incl. locally-derived gust/lull),
                              temp, humidity (received directly over RF),
                              rain_accumulation_mm/rain_rate_mmh (NOT locally
                              computed — see below), derived comfort metrics,
                              battery_low. UV/solar fields are defined but
                              essentially never populate — no sensor is
                              fitted on this ISS, and solar publishing is
                              disabled outright (see Known Issues). Also
                              includes station_pressure_mb/indoor_temperature_c/
                              indoor_humidity_pct from a BME280 soldered to the
                              receiver's ESP32 — local I2C readings, not
                              RF-decoded, and not part of the outdoor ISS.
                              sea_level_pressure_mb is computed on-device from
                              that same barometer on every reading (every
                              60s, no lag behind station_pressure_mb).
                              pressure_trend_mb/pressure_trend/
                              sea_level_pressure_trend_mb/
                              sea_level_pressure_trend are sampled separately
                              every 15 min (see Hardware Overview below) —
                              omitted from the payload for ~3h15m after every
                              boot until enough on-device history accumulates
    rapid_wind
    device_status
  davis-vantage-receiver/  ← Static control topics (device name, not station
    set_daily_rain             ID — not known at compile time): the ONLY
    set_rain_rate                writers of the rain fields above. The
                                  CC1101's own tip-derived rain calculation
                                  is disabled (unstable) — these topics,
                                  driven by the Meteobridge corrector below,
                                  are now the sole source
  airlink-<did>/           ← Davis AirLink air quality sensor (Python service)
    observation            — PM1/PM2.5/PM10, AQI, temperature, humidity
```

The Meteobridge corrector (`meteobridge/meteobridge_datalogger.py`) is not a station — it has no observation topic of its own. It only publishes to the `davis-vantage-receiver/set_daily_rain` / `set_rain_rate` control topics above, which are now the sole source for the Davis receiver's rain fields.

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
- Receiver: **ESP32-WROOM-32** (30-pin devkit) + **GERUI CC1101** — currently
  `frequency: 868.35MHz`, `filter_bandwidth: 650kHz` (narrowed from an original
  325kHz; this transmitter doesn't hop, so a tighter filter cuts noise without
  losing signal), CRC-16/CCITT with a 3-position bit-shift fallback
- Runs **ESPHome** firmware (`davis/davis-vantage-receiver.yaml`) which handles RF decoding and MQTT publishing
- HA entities come from ESPHome's own MQTT discovery (`mqtt: discovery: true`), grouped
  under one "Davis Vantage Receiver" device — same visual result as Tempest/AirLink's
  hand-rolled discovery, just via ESPHome's built-in mechanism instead. Entity names
  no longer repeat "Davis" (the device grouping already provides that context)
- `api:` is commented out by default — only needed for remote `esphome logs`/OTA over
  the native API; if enabled, this node must NOT also be added via Home Assistant's
  "ESPHome" integration UI, or entities would duplicate
- Local web dashboard at `http://<device-ip>/` (`web_server: port: 80`), including a
  diagnostic **Restart** button also discovered into HA
- **Status: active and field-tested — temperature/wind/humidity/gust/lull all
  reliable (gust and lull are both locally derived, not received over RF — see
  Known Issues). No UV or solar sensor is fitted; solar publishing is disabled
  entirely (RF noise made every "no sensor" sentinel check tried unreliable).
  Rain accumulation/rate: the CC1101 tip-derived calculation proved unstable
  and is disabled — `Daily Rain`/`Rain Rate` are now sourced exclusively from
  the Meteobridge corrector (see below)**
- A **BME280** is soldered directly to the receiver's ESP32 (I2C, `0x76`) —
  provides `Barometer`/`Indoor Temperature`/`Indoor Humidity`, polled locally
  every 60s, not RF-decoded and not part of the outdoor ISS. Published in the
  `observation` payload as `station_pressure_mb`/`indoor_temperature_c`/
  `indoor_humidity_pct`, and persisted to the `realtime`/`history`/
  `history_charting` tables via the existing `temp_humidity`(davis) role —
  see `combined_realtime`'s `davis_station_pressure_mb`/`indoor_temperature_c`/
  `indoor_humidity_pct` columns
- The receiver also computes its own **sea-level pressure + 3h trend**
  on-device from that same BME280 reading (same formula/±1mb thresholds as
  `tempest_datalogger.py`'s server-side version, just run in the ESPHome
  yaml instead) — `elevation_m`/`height_above_ground_m` substitutions at the
  top of the yaml feed the conversion. Sea-level pressure itself is
  recomputed via an `on_value:` trigger on the barometer sensor, so it
  tracks `station_pressure_mb` every 60s with no lag; the trend is sampled
  separately every 15 min with a 12-slot shift-and-append buffer (15 min x
  12 = exactly 3h) that needs no wall-clock/timestamp bookkeeping and isn't
  persisted across reboots, so trend is simply omitted from the payload for
  ~3h15m after every boot or reflash. Exposed in `combined_realtime` as
  `davis_sea_level_pressure_mb`/
  `davis_pressure_trend_mb`/`davis_pressure_trend`/
  `davis_sea_level_pressure_trend_mb`/`davis_sea_level_pressure_trend` —
  kept separate from Tempest's own `pressure` role fields (`pr.*` in the
  view), which remain the richer source if both a Tempest and a Davis
  receiver are present (Tempest's sea-level/trend is computed server-side
  with persisted history across restarts, vs. Davis' on-device/volatile
  version above)
- **Wet bulb, delta T, air density** are also computed on-device (same
  formulas as `tempest_datalogger.py`'s `_wet_bulb_c()`/`_air_density()` —
  wet bulb via a 50-iteration bisection solver), piggybacking on the
  existing comfort-metrics block since they need the same temp/humidity
  plus the BME280's station pressure. Exposed in `combined_realtime` as
  `davis_wet_bulb_c`/`davis_delta_t_c`/`davis_air_density_kgm3`, again kept
  separate from Tempest's `pr.wet_bulb_c`/`pr.delta_t_c`/`pr.air_density_kgm3`

### Davis AirLink
- Air quality sensor measuring PM1.0, PM2.5, and PM10 particulate matter
- Provides 2-min averages plus 1h/3h/24h averages and EPA NowCast values
- Local HTTP REST API at `http://<host>/v1/current_conditions` (no authentication required)
- `airlink_datalogger.py` polls the API every 60 s (configurable) and publishes to MQTT
- Temperature and humidity readings are included (device internal sensors, used for PM correction)
- AQI (US EPA) is computed from NowCast concentration before publishing
- CAQI (EU CITEAIR) is also computed, from *current* (not NowCast) concentration, added alongside the US AQI fields rather than replacing them (`caqi_pm2p5`/`caqi_pm10`)
- **Status: active**

### Meteobridge Pro (optional)
- Third-party bridge device, separately owned/configured, also wired to the same Vantage Vue ISS — not part of this project's own hardware, just a data source it can optionally consume
- Exposes a local REST template API (`cgi-bin/template.cgi?template=...`) where `[bracket]` macros are substituted server-side — see the [Meteobridge Add-On Services wiki](https://www.meteobridge.com/wiki/index.php?title=Add-On_Services)
- Proven consistent with the physical console — unlike the CC1101 receiver's own tip-derived rain calculation, which turned out unstable and has since been disabled entirely in the firmware
- `meteobridge_datalogger.py` polls it every 60s (configurable) and publishes rain_today/rain_rate to the Davis receiver's MQTT control topics — not its own station, no observation topic or database rows. Now the **sole** source for those two Davis entities, not just a correction layer
- **Status: active, optional** — the service idles (doesn't crash-loop) if `[meteobridge] host` is left unconfigured, but without it the Davis rain entities won't update at all

---

## Known Issues

### Davis Vantage Vue never receives RF gust packets — resolved by deriving gust locally

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
  produce it somehow — but by locally tracking the rolling max of its own wind
  samples over the last 60s, the same way the console evidently does, rather
  than by receiving a separate gust broadcast.

**Fix**: gust is now derived on-device the same way the console does it —
`wind_gust_max_ms` tracks the max of every `wind_avg_ms` sample (present in
every packet) since the last 60s tick, and is published as `davis_windgust`
on that tick (mirroring how wind lull is already the rolling min). The
`ptype == 9` handling is left in place and still takes priority if a real
gust packet is ever observed on different hardware. Confirmed working via
field testing. The on-device packet-type histogram/`CAL` logging used to
diagnose this is still in the yaml, commented out for quick re-enabling
(search `CALIBRATION (disabled)` in `davis-vantage-receiver.yaml`), useful if
this or the humidity/solar decoding ever needs re-validating on new hardware.

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
│   ├── meteobridge/                 ← Optional Meteobridge → Davis rain corrector
│   │   ├── meteobridge_datalogger.py ← Main Python service (HTTP polling → MQTT
│   │   │                                corrections, single file); no observation
│   │   │                                topic or database rows of its own
│   │   ├── requirements.txt        ← Runtime dependency: paho-mqtt
│   │   ├── systemd/
│   │   │   └── meteobridge-datalogger.service
│   │   └── README.md
│   ├── visualcrossing/              ← Optional Visual Crossing forecast poller
│   │   ├── visualcrossing_datalogger.py ← Main Python service (HTTP polling → MQTT,
│   │   │                                    single file); lat/lon-based, no station
│   │   │                                    hardware or Tempest account required
│   │   ├── requirements.txt        ← Runtime deps: paho-mqtt, pyVisualCrossing, aiohttp
│   │   ├── systemd/
│   │   │   └── visualcrossing-datalogger.service
│   │   └── README.md
│   ├── scripts/
│   │   └── deploy.sh               ← Pull from GitHub, install all services, run migrations
│   └── config.example.ini          ← Shared config template for all five services
├── davis/                           ← Davis Vantage Vue (ESPHome receiver)
│   ├── davis-vantage-receiver.yaml ← ESPHome firmware (CC1101 RF → MQTT); flashed
│   │                                  independently, not part of the LXC deploy
│   ├── scripts/
│   │   └── set_daily_rain.sh       ← Manual daily-rain correction helper; this one
│   │                                  IS deployed — installed by deploy.sh to
│   │                                  /opt/weatherdatalogger/scripts/
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
  - `meteobridge-datalogger` — files at `/opt/weatherdatalogger/meteobridge/`, venv at `.../meteobridge/venv` (optional — idles if `[meteobridge] host` is unset)
  - `visualcrossing-datalogger` — files at `/opt/weatherdatalogger/visualcrossing/`, venv at `.../visualcrossing/venv` (optional — idles if `[visualcrossing] enabled = false`)
- **Single shared config** at `/opt/weatherdatalogger/config.ini` — all five services read from this one file; never overwritten by the deploy script
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
| `combined_realtime` | View merging latest Davis (primary weather) + Tempest (pressure/lightning/UV/solar — sensors Davis lacks) + AirLink (air quality) into one row; use this for dashboards |
| `forecast_current`, `forecast_hourly`, `forecast_daily` | Latest Visual Crossing forecast fetch per `location` (not append-only); populated by `visualcrossing_datalogger.py` via `db_writer.py` |
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

All five services read from a single shared `config.ini`. The template with all documented keys is `config.example.ini` at the repo root (deployed to `/opt/weatherdatalogger/config.example.ini`).

Each service uses only the sections relevant to it — extra sections are ignored by `configparser`.

### Shared sections (all services)

| Section | Key settings |
|---|---|
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `retain`, `qos` — `meteobridge_datalogger.py` doesn't read `retain` (its corrections are always unretained, hardcoded) |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` — not used by `meteobridge_datalogger.py`, which creates no entities of its own |

> **Note:** `client_id` is NOT in the shared config — each service's `DEFAULT_CONFIG` provides its own unique default (`tempest-datalogger`, `airlink-datalogger`, `weatherdb-writer`, `meteobridge-datalogger`, `visualcrossing-datalogger`).

### tempest_datalogger.py

| Section | Key settings |
|---|---|
| `[udp]` | `listen_address`, `listen_port` |
| `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |

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

### meteobridge_datalogger.py

| Section | Key settings |
|---|---|
| `[meteobridge]` | `host` (optional — service idles rather than crash-loops if unset), `port` (80), `username` (default `meteobridge`, Meteobridge's own factory default — HTTP basic auth; empty sends no `Authorization` header), `password`, `interval_s` (60), `timeout_s` (10) |

### visualcrossing_datalogger.py

| Section | Key settings |
|---|---|
| `[visualcrossing]` | `enabled` (optional — service idles rather than crash-loops if false), `api_key`/`latitude`/`longitude` (**REQUIRED** if enabled), `days` (14, free-tier max), `language` (en), `location` (home), `interval_min` (60) |

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

Discovery is published once per device per run (tracked with an in-memory set). The `lightning_last_detected` sensor uses `device_class: timestamp` so HA displays it natively as "2 hours ago".

> **Forecast has no HA discovery.** `visualcrossing_datalogger.py` publishes plain data topics only (`forecast-<location>/{current,forecast_hourly,forecast_daily}`), unlike the WeatherFlow forecast poller it replaced (which auto-discovered 9 sensors plus a logged `template: weather:` YAML snippet — HA MQTT discovery doesn't support `weather` entities directly). Forecast data is intended to feed a future DB-driven Home Assistant custom integration instead, reading `forecast_current`/`forecast_hourly`/`forecast_daily` directly from MariaDB.

---

## Conventions

- Python: 3.13 on the production LXC; code written to be compatible with 3.11+ syntax (ruff target stays `py311`)
- Linting: ruff (`scripts/lint`), `select = ["ALL"]`, `target-version = "py311"`
- Logging: stdlib `logging`, level configurable in `config.ini`
- Config: `configparser` INI format
- Units: always SI in MQTT payloads; label field names with unit suffix
- MQTT QoS: default 0 (configurable), retain: default false (state topics), always true (HA discovery)
- Each service is a **single self-contained Python file** with its own `requirements.txt`
