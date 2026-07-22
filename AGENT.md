# AGENT.md — Instructions for AI Coding Assistants

This file gives AI assistants (Claude Code, Copilot, Cursor, etc.) the context
needed to contribute to this project effectively. Read CONTEXT.md first for the
full architecture overview.

---

## What this project is

A weather data pipeline with five active Python services:

1. **Tempest datalogger** (`tempest/tempest_datalogger.py`) — receives WeatherFlow Tempest UDP broadcasts, computes derived metrics, and publishes everything to MQTT
2. **AirLink datalogger** (`airlink/airlink_datalogger.py`) — polls the Davis AirLink's local REST API for air quality and publishes to MQTT
3. **DB writer** (`database/db_writer.py`) — subscribes to MQTT observation topics and persists readings to MariaDB (`realtime` + `history` tables), plus forecast topics into `forecast_current`/`forecast_hourly`/`forecast_daily`
4. **Meteobridge datalogger** (`meteobridge/meteobridge_datalogger.py`) — optional; polls a Meteobridge's local REST template API and publishes a full observation to MQTT (wind, pressure, temperature/humidity, solar/UV, rain, indoor, lightning) — a full station integration with its own database rows, not just a correction feed (see "Meteobridge datalogger" below)
5. **Visual Crossing forecast datalogger** (`visualcrossing/visualcrossing_datalogger.py`) — optional; lat/lon-based, polls the Visual Crossing Weather API via the `pyVisualCrossing` wrapper and publishes current/hourly/daily forecast to MQTT (no station hardware required — see "Visual Crossing forecast datalogger" below)

Two further, non-Python components live under `ESPHome/` (a sibling of `weatherdatalogger/` at the repo root) rather than as Python services:

- Davis Vantage Vue via an M5Stack Core (ESP32) + CC1101 module, running ESPHome firmware (`ESPHome/davis/davisnet-weatherlogger.yaml`) — see "Davis Vantage Vue (ESPHome firmware)" below
- A custom air quality monitor (ESP32-C6 + SDS011 + BME280), running ESPHome firmware (`ESPHome/airquality/air-quality-monitor.yaml`) — see "Air Quality Monitor (ESPHome firmware)" below

All station services/firmware publish under `weatherdatalogger/` so Home Assistant (or any MQTT subscriber) gets a unified feed.

---

## Coding conventions

- **Python 3.13** is the production runtime. Code must be compatible with **3.11+ syntax** (ruff target stays `py311` — do not change it)
- **Type hints** on all public function signatures
- **stdlib only** unless a library is already in the service's `requirements.txt`; ask before adding new dependencies
- **`configparser` INI** for all runtime config — never hardcode addresses, ports, or credentials
- **`logging`** (stdlib) for all output — no `print()` in production code
- Field names in MQTT JSON payloads: **descriptive snake_case with unit suffix** (`air_temperature_c`, `station_pressure_mb`, `wind_avg_ms`, `relative_humidity_pct`)
- Each service stays as a **single self-contained file** with its own `requirements.txt`
- **`VERSION`** (repo root, plain `X.Y.Z`) — bump it whenever you make a change worth telling users/operators apart by (new feature, schema/topic change, breaking config change, notable bug fix). `deploy.sh` reads it plus the deployed commit's short SHA and writes both to `/opt/weatherdatalogger/VERSION` on every deploy — that's what a user reports back when asking for a change or filing an issue, so keep it current rather than batching bumps
- **`CHANGELOG.md`** (repo root, [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)-ish) — add an entry under `## [Unreleased]` for anything that also earns a `VERSION` bump; when you bump `VERSION`, retitle `[Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and start a fresh empty `[Unreleased]` above it. Group entries under `### Added`/`### Changed`/`### Fixed` as needed; call out breaking changes explicitly (bold `**Breaking:**` prefix, see the `0.1.0` entry for the pattern) — this is the thing to check before assuming you know what's already deployed

---

## Critical: ruff target-version must stay "py311"

`.ruff.toml` has `target-version = "py311"`. **Do not change this.**

If bumped to `py314`, ruff will reformat `except (E1, E2):` → `except E1, E2:`
(PEP 758 syntax valid in 3.14 but a `SyntaxError` in 3.11). This has broken
production before. Always run `scripts/lint` after editing and check that
`except` clauses keep their parentheses.

---

## MQTT topic rules — follow these exactly

```
weatherdatalogger/tempest-<serial>/<message_type>
weatherdatalogger/forecast-<provider>-<location>/current|forecast_hourly|forecast_daily  (e.g. forecast-visualcrossing-home)
weatherdatalogger/davis-<station_id>/<sensor>
weatherdatalogger/aqmonitor-<id>/observation
```

- `<serial>` comes from the `serial_number` field in the UDP broadcast (`ST-00209955`, `HB-00013030`, etc.) with `:` replaced by `-`
- `<location>` is the config value lowercased with spaces replaced by `-`
- Subtopic names are lowercase with underscores
- Never publish to the bare `weatherdatalogger/` topic

---

## Tempest datalogger architecture

### Request flow
```
UDP broadcast → dispatch() → parse_<type>() → [compute_obs_derived()] → publish()
                                                       ↓
                                           [publish_ha_discovery()] (once per device)
```

### Adding a new message type
1. Write a `parse_<type>(msg: dict) -> dict | None` function in `tempest/tempest_datalogger.py`
2. Add an entry to `PARSERS`: `"type_string": ("subtopic_name", parse_fn)`
3. If it needs HA discovery, add sensor tuples to the appropriate `_*_SENSORS` list and register it in `_HA_DISCOVERY_MAP`

### Adding a new derived metric
1. Add the computation in `compute_obs_derived()` (or a helper called from it)
2. Add a sensor entry to `_ST_OBS_SENSORS`:
   `("field_name", "Friendly Name", "unit", "ha_device_class", "ha_state_class")`
   - Use `None` for device_class / state_class / unit when not applicable
   - HA device class `"timestamp"` is special: value must be ISO 8601 UTC string

### Persistence pattern
Both lightning history and pressure history use the same pattern:
- Module-level `list[dict]` (mutable, no `global` needed)
- Module-level `list[Path | None]` as a single-element mutable cell for the file path
- `init_*(cfg, config_path, log)` called once from `main()` — loads from disk, prunes old entries
- `record_*()` appends + prunes + saves on every event
- File location: `cfg["station"]["data_dir"]` or same directory as config file

---

## DB writer architecture

### Data flow
```
MQTT on_message() → _payload_to_row() → DbWriter.write_observation()
                                                ↓
                                   ensure_station()  (INSERT IGNORE)
                                   _execute(UPSERT realtime)
                                   _execute(INSERT history)
```

### Adding a new observation field to the database
1. Add a migration file `database/migrations/YYYYMMDD_add_<field>.sql` with `ALTER TABLE realtime ADD COLUMN IF NOT EXISTS …` and `ALTER TABLE history ADD COLUMN IF NOT EXISTS …` — use `IF NOT EXISTS` so the migration is idempotent on a fresh install where `02_create_tables.sql` already added the column
2. Add the same column to `02_create_tables.sql` so fresh installs have the complete schema without needing to run migrations
3. Add the field name to `_OBS_FIELDS` in `db_writer.py` (if it maps 1:1 from the payload) or handle it in `_payload_to_row()` (if it needs conversion, like `lightning_last_detected`)
4. The SQL column lists (`_COL_LIST`, `_PLACEHOLDERS`, `_UPDATE_CLAUSE`) are built from `_ALL_COLS` at import time — no further changes needed

### DB connection management
- `DbWriter._execute()` retries once on `OperationalError` **or `InterfaceError`** (lost connection), reconnecting via `_connect()` before the second attempt. Both error types must be caught: `OperationalError` fires on a failed new connection; `InterfaceError: (0, '')` fires when an existing connection is silently dropped (e.g. server restart).
- `autocommit=True` — no explicit transaction management needed for single-statement writes
- `_known_stations` is an in-memory set; it is rebuilt if the process restarts (safe — `INSERT IGNORE` is idempotent)

---

## Davis Vantage Vue (ESPHome firmware)

Unlike Tempest/AirLink, this is **not a Python service** — it's ESPHome YAML + inline C++ lambdas (`ESPHome/davis/davisnet-weatherlogger.yaml`) flashed to an M5Stack Core (ESP32) + CC1101 radio module. This supersedes an earlier ESP32-WROOM-32 + breakout-board build (`ESPHome/davis/davis-vantage-receiver.yaml`, kept for reference) — the RF decode/MQTT logic below is unchanged between the two; only the physical hardware and local display differ. Read `ESPHome/davis/README.md` for hardware/wiring and CONTEXT.md's "Known Issues" section before touching this file — several non-obvious RF findings are documented there and are expensive to re-derive.

### Packet flow
```
CC1101 on_packet (raw 8 bytes)
  → ESP_LOGD raw-arrival diagnostic (silent at default INFO level)
  → bit-reversal (LSB→MSB)
  → CRC-16/CCITT with 3-position bit-shift fallback → drop if all fail
  → station-ID lock (first valid ID seen; ignore other transmitter IDs after)
  → per-packet-type decode: wind every packet; temp=8, UV=3 (no sensor fitted),
    solar=5 (no sensor fitted, publishing disabled), humidity=10, rain-tip=14.
    Type 9 (Davis' own gust broadcast) is decoded if ever observed, but has
    never been seen on this hardware.
  → gust/lull derived locally (60s interval, rolling max/min of every packet's
    wind_avg_ms) — not from a dedicated packet type; see "Locally-derived
    gust/lull" below
  → rain rate derived per-tip from the actual gap since the previous tip; see
    "Rain accumulation & rate" below
  → comfort metrics computed from davis_temp/davis_hum (same formulas as
    tempest_datalogger.py)
  → consolidated `observation` JSON published to weatherdatalogger/davis-<id>/observation
```

### RF humidity
Packet type 10 (humidity) is decoded directly from RF (see `ptype == 10` in the packet-type decode) since `filter_bandwidth` was widened to 650 kHz. The earlier AirLink MQTT humidity fallback (`weatherdatalogger/airlink/humidity` → `davis_hum` via `mqtt: on_json_message`) has been removed now that RF humidity is reliable.

### Locally-derived gust/lull
Packet type 9 (gust) has never been observed on this hardware (confirmed by a 40-minute packet-type histogram — see CONTEXT.md "Known Issues"). `wind_gust_max_ms`/`wind_lull_min_ms` globals track the rolling max/min of `wind_avg_ms` (present in every packet) and publish on the 60s `interval:` tick, the same way the console's own display evidently computes it. The `ptype == 9` handler is left in place and still takes priority if a real gust packet is ever received on different hardware.

### Rain accumulation & rate
`davis_rain`/`davis_rain_rate` are computed **standalone from the ISS's own RF tip counter** (`ptype == 14`, 0.2mm/tip) — the same way the Davis console itself derives rain, no external station required. Rate is derived from the actual gap since the previous tip (not a fixed 60s bucket), decays to `0` if no tip has been seen for 5+ minutes (60s `interval:` block), and the daily total resets at local midnight via the `time:` (sntp) `on_time` trigger. `rain_total_mm`/`rain_count_prev` use `restore_value: yes` so a reboot doesn't lose the day's total or desync from the physical tip counter.

The `set_daily_rain`/`set_rain_rate` MQTT control topics (`mqtt: on_message:`) remain available as an **optional** manual/cross-check correction — e.g. to punch in the console's displayed value after a reflash/reboot that landed between tips, or via `ESPHome/davis/scripts/set_daily_rain.sh <mm>` — but nothing here depends on them. `meteobridge_datalogger.py` used to push automatic corrections into these same topics on a timer; it's since been rewritten into a full station integration (see "Meteobridge datalogger" below) and no longer touches them — Davis's own RF-tip-derived rain fields are unaffected either way. If you'd rather source `combined_realtime`'s `rain` role from Meteobridge's own reading instead of Davis's, that's a `station_roles` update (see below), not a firmware change.

### Solar radiation
No sensor is fitted on this Vantage Vue ISS. The `raw == 0x3FF` "no sensor" sentinel (and later a `raw >= 1000` tolerance band) both proved unreliable against RF noise on this 10-bit field — occasional noise landed low enough to slip through as a bogus reading (e.g. raw≈1021 decoding as a fake ~1795 W/m²). Publishing is now disabled entirely in the `ptype == 5` handler; the entity correctly reads "Unavailable" in HA. Raw values are still logged at `ESP_LOGD` for reference if a real sensor is ever fitted (search for `davis_solar_radiation` to re-enable).

### Meteobridge datalogger
`weatherdatalogger/meteobridge/meteobridge_datalogger.py` — HTTP poll → parse → publish MQTT, structurally like `airlink_datalogger.py`, but now a **full station integration**: publishes to `weatherdatalogger/meteobridge-<mac>/observation`, picked up by `db_writer.py` like any other station. Previously this service only pushed optional rain corrections into the Davis receiver's own entities and had no database rows of its own — see "Rain accumulation & rate" above; that correction was never depended on (Davis's rain fields are self-sufficient from the RF tip counter), so retiring it has no consequence to this device.

The Meteobridge is wired to the same Vantage Vue ISS as this ESPHome device, plus its own onboard barometer/indoor sensor and a second attached station providing solar/UV/lightning — so its fields overlap with `davis`'s. Which station actually supplies each `combined_realtime` field is controlled by the `station_roles` database table, not by either service — see `database/02_create_tables.sql`.

Requests use a single quote-free comma-separated template (`MB_TEMPLATE` — 30 macros covering wind/pressure/temp-humidity/solar-UV/rain/indoor/lightning/PM; see the comment block above `_TEMPLATE_FIELDS` in the script for which macro suffixes were validated against real hardware versus inferred by symmetry) — a JSON-shaped template was tried first but real hardware backslash-escaped every quote in the output (some Meteobridge firmware applies PHP/CGI-style `addslashes()`), breaking `json.loads`; the CSV format has nothing left for it to escape. Each macro carries a `:fallback` suffix so one missing sensor degrades that field instead of losing the whole poll. `wind_beaufort`/`wind_beaufort_description` are computed client-side from `wind_avg_ms` using the same WMO thresholds/English-Danish wording as this YAML's `beaufort_en`/`beaufort_da` tables (not Meteobridge's own `=bft` converter) so the numbers/wording match regardless of which station a role points at. Lightning has no per-strike timestamp macro on this hardware (`-time` suffix tried, unsupported) — new strikes are detected by watching Meteobridge's daily counter (`lgt0total-daysum`) increase between polls, then windowed into a 3h summary using the same persisted-history pattern `tempest_datalogger.py` uses for WeatherFlow's own discrete strike events, just fed from a polled counter instead.

**PM/air quality:** this Meteobridge has a PM sensor wired in as a comparison source to the dedicated Davis AirLink. Meteobridge's `air0pm`/`air1pm`/`air2pm` channels map to PM10/PM2.5/PM1.0 respectively — confirmed against real hardware readings (PM1.0 ≤ PM2.5 ≤ PM10 always holds physically), **not** the naive `air0pm→PM1`/`air2pm→PM10` guess a prior, separately-maintained SQL template had backwards. `-avg60` is the longest averaging window this sensor supports (`-avg180`/`-avg1440` for 3h/24h both silently returned `0` against real hardware) — 3h/24h averages and an EPA NowCast (weighted average of the last 12 hourly averages, same algorithm AirNow uses, requiring 2 of the most recent 3 hours to have data) are computed client-side from a persisted rolling sample buffer (`meteobridge_airquality.json`), the same pattern as the lightning window. `aqi_pm2p5`/`aqi_pm10`/`caqi_pm2p5`/`caqi_pm10` reuse `airlink_datalogger.py`'s exact breakpoint tables verbatim (each service stays self-contained, so these are duplicated rather than imported) — AQI from the client-computed NowCast, CAQI from the current (`-act`) concentration, matching AirLink's own NowCast-vs-current convention for the two index standards.

Optional: the service logs an error and idles (doesn't crash-loop) if `[meteobridge] host` is left unconfigured. Sends preemptive HTTP Basic Auth (`[meteobridge] username`/`password`, default username `meteobridge` — Meteobridge's own factory default) unless username is blank. Assumes Meteobridge is configured for metric units. See `weatherdatalogger/meteobridge/README.md`.

### Debugging this file
- Diagnostic/calibration logging used to investigate the packet-type histogram is **only present in the superseded `ESPHome/davis/davis-vantage-receiver.yaml`**, commented out (search `CALIBRATION (disabled)`) — it was not carried over into `davisnet-weatherlogger.yaml`. Port it over (or temporarily flash the old yaml) to re-run the same test against different CC1101 hardware, rather than re-deriving the approach from scratch.
- A raw-packet-arrival log (`ESP_LOGD("davis", "Raw packet received: ...")`, silent at the default `INFO` level) sits right before the CRC check. Set `logger: level: DEBUG` and reflash if packets ever stop being logged, to distinguish "CC1101 isn't receiving RF frames at all" (this line never appears — hardware/RF issue, check the CC1101 module's DIP switches first) from "frames arrive but fail CRC" (this line appears but no `Packet type: ...` ever follows — decode-side issue). Revert to `INFO` afterward — `DEBUG` logs a line per packet (~every 2.5s) indefinitely otherwise.
- `esphome logs ESPHome/davis/davisnet-weatherlogger.yaml` for remote logs requires the native API — the `api:` block in the YAML is commented out by default; uncomment it (and provide `api_encryption_key` in `secrets.yaml`) temporarily if you need this. Do **not** also add this node via Home Assistant's "ESPHome" integration UI if you do, since HA entities come from `mqtt: discovery: true` instead, and having both would duplicate every entity.

---

## Air Quality Monitor (ESPHome firmware)

Also **not a Python service** — ESPHome YAML + inline C++ lambdas (`ESPHome/airquality/air-quality-monitor.yaml`) flashed to an ESP32-C6-DevKitC-1 with an SDS011 (PM2.5/PM10, UART) and a BME280 (temperature/humidity/pressure, I2C). Read `ESPHome/airquality/README.md` for hardware/wiring and field conventions before touching this file.

Like the Davis receiver, this device connects to Home Assistant via ESPHome's own **MQTT discovery** (`mqtt: discovery: true`), grouping all entities under one device. `time:` uses `sntp`, not `homeassistant`, so this device's data path stays independent of whether it's ever added via HA's native ESPHome integration — same reasoning as the Davis receiver. `api:` is commented out by default, kept solely for remote `esphome logs`/OTA if enabled; do **not** also add this node via HA's "ESPHome" integration UI if you do, since entities would then be duplicated (once via native API, once via MQTT discovery). `reboot_timeout: 0s` is set explicitly from the start, learning from the Davis `reboot_timeout` incident below.

### Data flow
```
SDS011 on_value (~every 5 min, sensor's own duty cycle)
  → publish PM2.5/PM10, persist to flash-backed globals (boot restore)
  → recompute AQI/CAQI sub-index sensors immediately (id(...).update()),
    rather than waiting for their own update_interval to drift out of
    phase with the SDS011's timing
BME280 (every 60s)
  → temperature/humidity/pressure published directly
  → dew point recomputed (Magnus formula, same as davisnet-weatherlogger.yaml)
interval: (every 60s)
  → consolidated `observation` JSON published to
    weatherdatalogger/aqmonitor-<id>/observation, using the latest known
    value of every field (same "publish latest known state" convention as
    the Davis receiver's per-packet observation)
```

### AQI/CAQI — field-compatible with AirLink, not bit-identical
`aqi_pm2p5`/`aqi_pm10`/`caqi_pm2p5`/`caqi_pm10` are published so `db_writer.py` stores them in the same `_OBS_FIELDS` columns AirLink uses — same scale/definition, but **not** numerically identical at the same concentration:
- AQI here uses the EPA's May-2024-updated breakpoint table (matching the pre-existing single "AQI" display sensor already in this file) computed from the SDS011's **instantaneous** reading; `airlink_datalogger.py` uses an older breakpoint table computed from a 12h **NowCast**-smoothed concentration. This device has no on-device rolling-average buffer to replicate NowCast — see `ESPHome/airquality/README.md`'s "Field conventions" for the full caveat.
- CAQI uses the same breakpoint tables and current-concentration convention as `airlink_datalogger.py`'s `_caqi_pm2p5`/`_caqi_pm10` (duplicated, not imported — same self-contained-service principle as every other station integration in this project).

There's no PM1.0 and no 1h/3h/24h averages on this hardware (SDS011 only reports instantaneous PM2.5/PM10) — those `_OBS_FIELDS` columns simply stay `NULL` for `station_type = 'aqmonitor'` rows.

### `air_quality` role
This device registers as its own `station_type` (`aqmonitor`, from the `aqmonitor-<id>` topic segment) — a separate station from `airlink`. `station_roles`' `air_quality` role still defaults to `airlink`; reassign it (`UPDATE station_roles SET station_type = 'aqmonitor' WHERE role = 'air_quality';`) to make `combined_realtime`/`history_charting` read from this device instead — see `ESPHome/airquality/README.md`.
- Repeating `[I][safe_mode:142]: Boot seems successful` lines in the log are the tell for a reboot loop, even when nothing else looks wrong — check `reboot_timeout` settings (`mqtt:`, `api:`, `wifi:`) if this shows up more than once per intentional flash. A single occurrence right after a flash/reboot is normal.
- A local web dashboard is available at `http://<device-ip>/` (`web_server: port: 80`), including a diagnostic **Restart** button (`button: platform: restart`) — also discovered into HA as a diagnostic entity.

---

## Config sections

All five services (tempest, airlink, db_writer, meteobridge, visualcrossing) share a single config file at `/opt/weatherdatalogger/config.ini`. Each service reads only the sections it needs — extra sections are ignored. The full template is `config.example.ini` at the repo root.

`client_id` is **not** in the shared config — each service's `DEFAULT_CONFIG` provides its own unique value so they don't collide on the MQTT broker.

### Shared sections (all services)

| Section | Notable keys |
|---|---|
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `retain`, `qos` |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` |

### Service-specific sections

| Service | Section | Notable keys |
|---|---|---|
| `tempest_datalogger.py` | `[tempest]` | `enabled` (**default false** — service idles until set true) |
| | `[udp]` | `listen_address`, `listen_port` |
| | `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |
| `airlink_datalogger.py` | `[airlink]` | `enabled` (**default false**), `host` (**REQUIRED** if enabled), `port` (80), `interval_s` (60), `timeout_s` (10) |
| `db_writer.py` | `[database]` | `host`, `port`, `name`, `user`, `password` (**REQUIRED**) |
| `meteobridge_datalogger.py` | `[meteobridge]` | `enabled` (**default false**), `host` (**REQUIRED** if enabled), `port` (80), `username` (default `meteobridge`, Meteobridge's own factory default — empty sends no `Authorization` header), `password`, `interval_s` (60), `timeout_s` (10), `language` (en/da, for `wind_beaufort_description`), `data_dir` (lightning-window state file) |
| `visualcrossing_datalogger.py` | `[visualcrossing]` | `enabled` (**default false** — service idles if false), `api_key`/`latitude`/`longitude` (**REQUIRED** if enabled), `days` (14), `language` (en), `location` (home), `interval_min` (60) |

All four services now share the same `enabled` gate (checked first in `run()`,
before connecting to MQTT), defaulting to `false` so a fresh install doesn't
try to log hardware/APIs it doesn't have. If `config.ini` predates this flag
(no explicit `enabled` key for that section), the service logs a one-time
`WARNING` explaining the new default instead of silently idling — see
`_enabled_key_present()` in each `*_datalogger.py`.

`data_dir` (tempest) defaults to `/opt/weatherdatalogger/tempest`. That is where `tempest_lightning.json` and `tempest_pressure.json` are written.

---

## MQTT client

Both services use `paho.mqtt.client` with `loop_forever()` or `loop_start()`:
- **Tempest datalogger**: `loop_start()` (background thread) — main thread runs the UDP receive loop
- **DB writer**: `loop_forever()` — MQTT is the only I/O; blocking loop is appropriate
- Auto-reconnects via `on_disconnect` callback in both services

---

## HA discovery (tempest datalogger only)

- One retained config message per sensor to `<prefix>/sensor/<unique_id>/config`
- Published once per device per process run (tracked by `_discovered` set)
- Device info (`_device_info()`) distinguishes hub (`HB-`) from sensor (`ST-`)
- `_HA_DISCOVERY_MAP` maps UDP type → (subtopic, sensor_list)

**Forecast has no HA discovery.** `visualcrossing_datalogger.py` publishes plain data topics only (`forecast-<provider>-<location>/{current,forecast_hourly,forecast_daily}`) — no MQTT discovery sensors, unlike the old WeatherFlow forecast thread this replaced (which published 9 auto-discovered sensors plus a `template: weather:` YAML snippet). Forecast consumption is moving to a DB-driven Home Assistant custom integration reading `forecast_current`/`forecast_hourly`/`forecast_daily` directly (see `database/README.md`) rather than MQTT discovery, so that layer was deliberately not rebuilt for Visual Crossing.

---

## Dev environment

The devcontainer cannot receive real Tempest UDP broadcasts (Docker Desktop on
macOS runs in a Linux VM; LAN broadcasts never reach it). Use the simulator:

```bash
python3 tempest/scripts/simulate_udp.py          # sends all 6 message types once
python3 tempest/scripts/simulate_udp.py --count 0 --interval 60  # continuous, every 60s
```

Subscribe to verify MQTT output:
```bash
mosquitto_sub -h localhost -t 'weatherdatalogger/#' -v
```

Run the datalogger:
```bash
python3 tempest/tempest_datalogger.py --config tempest/config.dev.ini
```

The DB writer requires a reachable MariaDB instance — point `[database] host` at your production LXC or run a local MariaDB container for dev testing.

---

## Linting

```bash
bash scripts/lint      # ruff format + ruff check --fix
```

`select = ["ALL"]` with a small ignore list. Common suppressions needed:
- `# noqa: PLR2004` on comparisons against named meteorological thresholds
- `# noqa: BLE001` on intentional broad `except Exception` catches
- `# noqa: S104` on `0.0.0.0` bind address
- `# noqa: TRY400` on `log.error()` inside retry loops (TRY400 wants `log.exception()`)

---

## What's already done ✅

### AirLink datalogger
- [x] HTTP polling service (`airlink/airlink_datalogger.py`) — polls `/v1/current_conditions` every 60 s
- [x] Publishes PM1/PM2.5/PM10, AQI, temperature, humidity to `weatherdatalogger/airlink-<did>/observation`
- [x] AQI computed from NowCast using US EPA breakpoints
- [x] CAQI (EU CITEAIR) also computed, from *current* (not NowCast) concentration — different index philosophy than US AQI (real-time hourly vs. 12h-smoothed). Added alongside `aqi_pm2p5`/`aqi_pm10`, not replacing them — `caqi_pm2p5`/`caqi_pm10`. Official bands only go to 100; extrapolated (same slope, capped at 200) beyond that rather than returning `None`
- [x] Temperature/dew point converted from °F → °C
- [x] HA MQTT discovery (20 sensors auto-discovered)
- [x] INI config with documented defaults (`airlink/config.example.ini`)
- [x] systemd service unit (`airlink/systemd/airlink-datalogger.service`)
- [x] DB migrations: `database/migrations/20260629_add_airquality.sql` (PM + US AQI columns), `database/migrations/20260702_add_caqi.sql` (CAQI columns, also threaded through `combined_realtime` and `history_charting`)
- [x] DB writer updated — PM/AQI/CAQI fields added to `_OBS_FIELDS`

### Tempest datalogger
- [x] UDP listener with all 6 message type parsers
- [x] MQTT publish with configurable base topic, QoS, retain, TLS
- [x] INI-based config with documented defaults (`tempest/config.example.ini`)
- [x] Dev config for devcontainer (`tempest/config.dev.ini`)
- [x] systemd service unit (`tempest/systemd/tempest-datalogger.service`)
- [x] UDP packet simulator (`tempest/scripts/simulate_udp.py`)
- [x] Home Assistant MQTT discovery (all raw + derived sensors auto-discovered)
- [x] Derived metrics: dew point, wet bulb, delta T, feels like, heat index, wind chill, vapor pressure, air density, rain rate, sea level pressure
- [x] Station and sea level pressure trend (3h, persisted across restarts)
- [x] Lightning history: last detected timestamp, 3h count, 3h min/max distance (persisted)
- [x] ~~WeatherFlow Better Forecast REST API poller~~ — removed; replaced by the standalone Visual Crossing forecast datalogger below (no longer tied to a Tempest station)

### Visual Crossing forecast datalogger
- [x] New service `weatherdatalogger/visualcrossing/visualcrossing_datalogger.py` — replaces the WeatherFlow Better Forecast poller that used to live in `tempest_datalogger.py`. Lat/lon-based (via the `pyVisualCrossing` wrapper), so it has no dependency on a registered Tempest station or WeatherFlow account at all
- [x] Originally published to the same topic shape the WeatherFlow forecast used (`forecast-<location>/{current,forecast_hourly,forecast_daily}`) so `db_writer.py`'s existing subscription needed no routing changes at the time — only the field/column set changed. Later widened to `forecast-<provider>-<location>/...` (see below) once a second forecast provider became a real possibility
- [x] Richer field set than WeatherFlow's forecast: adds `feels_like_c`, `cloud_cover_pct`, `wind_gust_ms`, `uv_index` (plus `visibility_km`/`solar_radiation_wm2` on current conditions only)
- [x] `_VC_ICON_TO_HA` maps Visual Crossing's `icons2` icon set to HA weather conditions — a different vocabulary from WeatherFlow's own icon set, same role as the old `_WF_ICON_TO_HA`
- [x] No MQTT HA discovery (deliberate) — forecast consumption is moving to a DB-driven HA custom integration instead; see `database/README.md`
- [x] Optional service — logs an error and idles (doesn't crash-loop) if `[visualcrossing] enabled = false` or `api_key`/`latitude`/`longitude` aren't all set
- [x] Full service scaffold: `config.example.ini`, `requirements.txt`, `systemd/visualcrossing-datalogger.service`, `README.md`
- [x] `[visualcrossing]` section added to the shared `weatherdatalogger/config.example.ini`
- [x] `forecast_current`/`forecast_hourly`/`forecast_daily` DB tables replaced outright (not extended) for the new field set — `database/migrations/20260707_add_forecast_tables.sql`
- [x] `provider` dimension added later — MQTT topic became `forecast-<provider>-<location>/...` and the three tables' keys became `(provider, location[, forecast_time])`, so a second forecast provider (Pirate Weather, WeatherFlow Better Forecast, ...) can run alongside Visual Crossing without colliding on the same location. `visualcrossing_datalogger.py`'s `FORECAST_PROVIDER = "visualcrossing"` constant is the slug; `db_writer.py` parses it by partitioning the topic segment on the first `-` — see `database/migrations/20260713_add_forecast_provider.sql`
- [x] Note for future maintainers: `pyVisualCrossing` 0.1.16 imports `aiohttp` unconditionally at module load (for its unused async path) but doesn't declare it as a dependency — listed explicitly in `visualcrossing/requirements.txt`

### Database
- [x] MariaDB on the same LXC, bound to `0.0.0.0:3306` for network access
- [x] `stations`, `realtime`, `history`, `schema_migrations` tables — all with PM/AQI columns included from the start in `02_create_tables.sql`
- [x] DB writer service (`database/db_writer.py`) subscribing to `weatherdatalogger/+/observation`
- [x] Auto-registration of new stations on first observation
- [x] Upsert into `realtime`; append into `history` on every message
- [x] Reconnects on both `OperationalError` and `InterfaceError` (server restart safe)
- [x] All timestamps stored in UTC (db_writer uses `datetime.fromtimestamp(..., tz=UTC)`)
- [x] systemd service unit (`database/systemd/weatherdb-writer.service`) with `After=mariadb.service` and `Restart=on-failure`
- [x] Migration system: numbered SQL files in `database/migrations/`, tracked in `schema_migrations`; migrations use `ADD COLUMN IF NOT EXISTS` for idempotency
- [x] `combined_realtime` view — merges latest readings from `davis` (primary weather), `tempest` (pressure/lightning/UV/solar/wet-bulb/delta-T/air-density/battery-volts — sensors the Davis ISS lacks), and `airlink` (air quality) into one row; LEFT JOINs so it works without Tempest/AirLink registered (`database/migrations/20260702_davis_primary_combined_view.sql`)
- [x] `history_charting` table — pre-aggregated 10-minute combined windows (one row per clock-aligned UTC window), same Davis/Tempest/AirLink source split as the view; field aggregations: AVG for temperature/pressure/humidity/solar, MIN for lull, MAX for gust/rain rate, circular AVG for wind direction, SUM for rain accumulation, MAX for AQI/low-battery
- [x] `evt_aggregate_history_charting` MariaDB event — fires every 10 min, 30-min lookback, `INSERT IGNORE` for idempotency; uses `UTC_TIMESTAMP()` throughout (not `NOW()`) to match UTC-stored `recorded_at`
- [x] MariaDB event scheduler enabled via `/etc/mysql/mariadb.conf.d/99-local.cnf`

### Davis Vantage Vue (ESPHome)
- [x] ESPHome firmware (`ESPHome/davis/davisnet-weatherlogger.yaml`) — CC1101 packet decode, CRC validation, station-ID lock
- [x] Rebuilt on an M5Stack Basic Core + M5Stack CC1101 module (external antenna) — superseding the original ESP32-WROOM-32 + GERUI CC1101 breadboard build (`ESPHome/davis/davis-vantage-receiver.yaml`, kept for reference). RF decode/MQTT topics/fields unchanged; local display switched from a time-cycled I2C OLED to the Core's built-in MIPI SPI LCD with button-driven paging. Device name for HA grouping and the static rain-correction MQTT topic changed from `davis-vantage-receiver` to `davisnet-datalogger`
- [x] Field-tested against real hardware — temperature/wind speed+direction/rain(+rate)/wind lull/gust/battery-low all reliable
- [x] Derived comfort metrics computed on-device (dew point, vapor pressure, heat index, wind chill, feels like) — same formulas as `tempest_datalogger.py`
- [x] `battery_low` DB column added (`database/migrations/20260701_add_battery_low.sql`)
- [x] Promoted to primary weather source in `combined_realtime`/`history_charting`, now that it's field-tested — Tempest kept only for pressure/lightning/UV/solar/wet-bulb/delta-T/air-density/battery-volts, which Davis doesn't sense (`database/migrations/20260702_davis_primary_combined_view.sql`)
- [x] HA integration via ESPHome's own `mqtt: discovery: true` (one grouped device), not the native API — entity names no longer repeat "Davis" (device grouping already provides that context in HA)
- [x] RF frequency/filter empirically recentred; currently `frequency: 868.35MHz` / `filter_bandwidth: 650kHz` — narrowed from an original 325kHz since this transmitter doesn't hop
- [x] `reboot_timeout: 0s` — was 15s, which force-rebooted the device on routine MQTT hiccups
- [x] RF humidity (ptype 10) now received directly since widening `filter_bandwidth` to 650 kHz — AirLink MQTT humidity fallback removed
- [x] Wind gust and lull both locally-derived — packet type 9 (Davis' own gust broadcast) is never sent by this ISS; gust is computed as the rolling max (lull as rolling min) of the ordinary wind samples present in every packet, over each 60s interval. Confirmed working. If a real ptype-9 packet is ever observed, it still takes priority. See CONTEXT.md "Known Issues".
- [x] Rain rate switched from a fixed 60s bucket-sum to per-tip tip-interval calculation (mirrors the console's own algorithm) — updates immediately per tip instead of quantizing to arbitrary clock windows; decays to 0 after 5 minutes without a tip (tunable, was 20 minutes initially); also explicitly zeroed on boot (see "Rain accumulation & rate" above — without this a stale pre-reboot value would persist in HA indefinitely if it doesn't rain again after a reboot).
- [x] Daily rain total (`rain_total_mm`) persisted across reboots via `restore_value: yes` (paired with the `rain_count_prev` tip-counter baseline), published immediately on boot via `esphome: on_boot:` so it reads 0/actual instead of "Unknown", and reset to 0 once daily at local midnight via a `time: (sntp)` component.
- [x] Manual daily-rain and rain-rate correction — publish to the static MQTT control topics `weatherdatalogger/davisnet-datalogger/set_daily_rain` / `set_rain_rate`, or run `ESPHome/davis/scripts/set_daily_rain.sh <mm>` (installed by `deploy.sh` to `/opt/weatherdatalogger/scripts/`).
- [x] Solar radiation publishing disabled entirely — no sensor is fitted on this Vue, and RF noise on the 10-bit field made every "no sensor" sentinel check tried (exact `raw == 0x3FF` match, then a `raw >= 1000` tolerance band) unreliable enough that occasional garbage still got published as a fake reading. Entity now correctly reads "Unavailable"; raw values still logged at DEBUG for reference.
- [x] Diagnostic "Restart" button (`button: platform: restart`) — available on the local web UI (`web_server: port: 80`) and as a diagnostic entity in HA.

### Air Quality Monitor (ESPHome)
- [x] ESPHome firmware (`ESPHome/airquality/air-quality-monitor.yaml`) — ESP32-C6 + SDS011 (PM2.5/PM10) + BME280 (temperature/humidity/pressure)
- [x] `mqtt:` block added, `discovery: true` (HA entities via MQTT discovery, same as the Davis receiver — `api:` is commented out, `time:` uses `sntp` not `homeassistant`), `reboot_timeout: 0s` set from the start (learned from the Davis `reboot_timeout` incident, see "Known Issues")
- [x] Consolidated `observation` JSON published every 60s to `weatherdatalogger/aqmonitor-<id>/observation`, latest-known-value convention like Davis's per-packet publish
- [x] Dew point computed on-device (Magnus formula, same as `davisnet-weatherlogger.yaml`/`tempest_datalogger.py`)
- [x] `AQI PM2.5`/`AQI PM10`/`CAQI PM2.5`/`CAQI PM10` sensors added — publish as `aqi_pm2p5`/`aqi_pm10`/`caqi_pm2p5`/`caqi_pm10`, same DB columns as AirLink, not bit-identical values (see "Air Quality Monitor (ESPHome firmware)" above for why)
- [x] No code/schema changes needed — reuses `db_writer.py`'s existing `_OBS_FIELDS` PM/AQI/CAQI columns and generic topic-segment station-type parsing (`aqmonitor-<id>` → `station_type = 'aqmonitor'`)
- [x] `ESPHome/airquality/README.md` — hardware, MQTT topics, field conventions, HA integration, `station_roles` reassignment instructions

### Meteobridge datalogger
- [x] ~~New service polling a Meteobridge Pro's REST template API and republishing rain_today/rain_rate as corrections to the Davis receiver's own MQTT control topics; not a full station integration — no observation topic, no database rows~~ — **superseded**, see below.
- [x] ~~Promoted to the sole source for `davis_rain`/`davis_rain_rate`~~ — that claim was itself stale by the time of this rewrite: Davis's rain fields had already been changed to compute standalone from the RF tip counter, with Meteobridge correction demoted to an optional cross-check. The correction push is now retired entirely; Davis's rain fields are unaffected either way. See "Rain accumulation & rate" above.
- [x] Rewritten as a **full station integration** — publishes wind, pressure (+ 3h trend), outdoor temperature/humidity/dew point/wet bulb/heat index/wind chill, solar/UV, rain, indoor temperature/humidity, and a lightning summary to `weatherdatalogger/meteobridge-<mac>/observation`, picked up by `db_writer.py` like any other station
- [x] `wind_beaufort`/`wind_beaufort_description` computed client-side using the same WMO thresholds and English/Danish wording as `davisnet-weatherlogger.yaml`'s `beaufort_en`/`beaufort_da`, not Meteobridge's own `=bft` converter
- [x] `feels_like_c`/`vapor_pressure_mb`/`air_density_kgm3` computed client-side with the same formulas as `tempest_datalogger.py`; `delta_t_c` = `air_temperature_c - wet_bulb_c`
- [x] Lightning: no per-strike timestamp macro on this hardware — new strikes detected by watching Meteobridge's daily strike counter (`lgt0total-daysum`) increase between polls, then windowed into a persisted rolling 3h summary the same way `tempest_datalogger.py` windows WeatherFlow's own discrete strike events
- [x] Which station actually supplies each `combined_realtime` field is controlled entirely by the `station_roles` database table (`UPDATE station_roles SET station_type = 'meteobridge' WHERE role = '...'`) — no code change needed to prefer this station over Davis/Tempest/AirLink for a given role
- [x] Optional service — logs an error and idles (doesn't crash-loop) if `[meteobridge] host` is left unconfigured
- [x] HA MQTT discovery added (previously had none, since it published no entities of its own)
- [x] Macro suffixes validated against real hardware before finalizing the template — several guesses were wrong in practice (`lgt0total-act` returned a nonsensical `"0%"`; `-daysum` works cleanly, matching `rain0total`'s own convention) — see the comment block above `_TEMPLATE_FIELDS` in the script
- [x] PM/AQI added: `air0pm`/`air1pm`/`air2pm` = PM10/PM2.5/PM1.0 (validated by physical PM1.0≤PM2.5≤PM10 ordering against live readings — a prior, separately-maintained SQL template had this backwards); `-avg60` is the longest native averaging window this sensor supports, so 3h/24h averages and an EPA NowCast (weighted 12-hourly-average, ≥2-of-last-3-hours-required) are computed client-side from a new persisted buffer (`meteobridge_airquality.json`); `aqi_pm2p5`/`aqi_pm10`/`caqi_pm2p5`/`caqi_pm10` reuse `airlink_datalogger.py`'s exact breakpoint tables

### Infrastructure
- [x] Top-level deploy script (`scripts/deploy.sh`) — staging clone, installs all five services under `/opt/weatherdatalogger/`, applies DB migrations, updates all venvs, enables+restarts services per `config.ini`
- [x] `systemctl status` in deploy uses `--lines=20 || true` — avoids hanging and tolerates services still in "activating" state
- [x] Single shared config at `/opt/weatherdatalogger/config.ini` — all services read from one file; auto-generates `db.cnf` for MySQL client
- [x] Ruff linting (`scripts/lint`, `.ruff.toml`)
- [x] `deploy.sh` also installs `ESPHome/davis/scripts/set_daily_rain.sh` to `/opt/weatherdatalogger/scripts/` — `ESPHome/` sits at the repo root as a sibling of `weatherdatalogger/`, not inside it, so this needed an explicit install step (`$STAGING/ESPHome/davis/...`, not `$STAGING_WDL/...`) even though the Davis ESPHome firmware itself is flashed independently and isn't otherwise part of the server deploy. The Air Quality Monitor (`ESPHome/airquality/`) needs no such step — it has no server-side helper script, unlike Davis's rain-correction one
- [x] `deploy.sh`'s restart loop is config-driven, not just systemd-driven: for each service it computes `should_run` from `config.ini` (`[section] enabled` for station/forecast services; "`config.ini` exists at all" for `weatherdb-writer`, which has no `enabled` flag of its own) and, if true, `systemctl enable`s it (if not already) then restarts — regardless of prior systemd state. If `should_run` is false it only ever skips/warns, **never** auto-disables or stops an already-running service; turning one off is always a manual `systemctl disable --now`. The `_config_enabled()` helper shells out to Python/`configparser` (same pattern as the `db.cnf` generator above it), with `fallback=False` covering both "no `config.ini` yet" and "config predates the `enabled` flag"
- [x] `scripts/install.sh` — one-time (but safely re-runnable) bootstrap for a fresh Debian host: OS packages, service user, MariaDB (network bind-address + event scheduler, each guarded so re-running is a no-op once already set), database + app user (password auto-generated only if the app user doesn't exist yet), schema creation, then a short interactive wizard (MQTT broker, which stations/forecast provider you have) that writes `config.ini` for you — skipped entirely if `config.ini` already exists, so it never clobbers a configured install. Calls `deploy.sh` twice: once before the wizard (installs files so `01_create_database.sql`/`02_create_tables.sql` exist on disk), once after (`config.ini` now has real values, so migrations apply and services enable+start per the point above). Writes `config.ini` via a comment-preserving line-based Python helper (`_set_config_values()`), not `configparser` — `configparser` would silently strip every comment in the template on write. Secret-valued prompts (`MQTT_PASSWORD`, `VC_API_KEY`) use `_ask_secret()` (`read -s`, hidden input) rather than `_ask()`
- [x] `database/03_create_readonly_user.sql` + `scripts/create_ha_readonly_user.sh` — creates a `SELECT`-only `weatherdatalogger_ha` MariaDB user for the separate [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) Home Assistant integration repo, which reads this database directly rather than over MQTT. The `.sh` script is the one to actually use (idempotent — skips and tells you how to rotate the password instead if the user already exists; prompts for the password rather than generating one, since the human has to manually re-enter it into the other project's config flow UI anyway); the `.sql` file is kept only as a manual-run reference matching `01_create_database.sql`'s style. `install.sh`'s wizard offers to run this script once, at first-time setup, gated behind "will you be installing that integration?" — declining there (or adding the integration later) means running `create_ha_readonly_user.sh` standalone instead, which is why it's a separate script rather than inlined wizard logic

## What's next / TODO

- [ ] Dashboard / charting — Grafana or similar consuming `history_charting` for 10-min resolution charts and `history` for raw data
- [ ] Unit tests for parser functions (no network required, just dicts in / dict out)
- [ ] Health/watchdog topic: `weatherdatalogger/tempest-<serial>/status` with `online`/`offline` LWT and last-seen timestamp

---

## Things to avoid

- Do not introduce async frameworks (asyncio, trio) — the current threading model is intentional and simple
- Do not add database write logic to `tempest_datalogger.py` — MQTT is its only output; the DB writer is the correct place
- Do not insert directly into `realtime` or `history` without first ensuring the station exists in `stations` — the foreign key will reject it
- Do not change the MQTT topic structure without updating CONTEXT.md and the HA discovery sensor list
- Do not store secrets in committed files — `config.ini` files are gitignored
- Do not bump `target-version` in `.ruff.toml` past `py311` without verifying production Python version and checking for syntax-breaking reformats (especially `except` clauses)
- Do not use `NOW()` in DB queries or events — `recorded_at` is stored in UTC; use `UTC_TIMESTAMP()` to avoid a mismatch when the MariaDB server runs in a non-UTC timezone
- Do not use `ADD COLUMN` without `IF NOT EXISTS` in migration files — `02_create_tables.sql` is the canonical full schema for fresh installs; migrations must be idempotent so they can run safely on either a fresh or an upgraded database
- Do not assume an MQTT `+` wildcard can match part of a topic level — it must occupy an entire level (`airlink-+` is invalid; `+` or `airlink-<did>` literal are the only valid forms). If a subscriber needs to reach a dynamically-generated topic segment (like the AirLink's runtime-discovered device id), publish an additional fixed-name convenience topic instead of trying to wildcard around it
- Do not set aggressive `reboot_timeout` values (e.g. ESPHome's `mqtt:`/`api:` components) without accounting for normal network flakiness — a 15s MQTT `reboot_timeout` caused the Davis receiver to silently reboot every 10-25 minutes on routine broker hiccups, resetting in-memory state each time. Repeating `Boot seems successful` log lines are the tell
