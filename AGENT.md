# AGENT.md — Instructions for AI Coding Assistants

This file gives AI assistants (Claude Code, Copilot, Cursor, etc.) the context
needed to contribute to this project effectively. Read CONTEXT.md first for the
full architecture overview.

---

## What this project is

A weather data pipeline with four active Python services:

1. **Tempest datalogger** (`tempest/tempest_datalogger.py`) — receives WeatherFlow Tempest UDP broadcasts, computes derived metrics, and publishes everything to MQTT
2. **AirLink datalogger** (`airlink/airlink_datalogger.py`) — polls the Davis AirLink's local REST API for air quality and publishes to MQTT
3. **DB writer** (`database/db_writer.py`) — subscribes to MQTT observation topics and persists readings to MariaDB (`realtime` + `history` tables)
4. **Meteobridge corrector** (`meteobridge/meteobridge_datalogger.py`) — optional; polls a Meteobridge Pro and republishes rain corrections to the Davis receiver's MQTT control topics (not a full station integration — see "Meteobridge corrector" below)

A fifth, non-Python component handles Davis Vantage Vue via ESP32 + CC1101, running ESPHome firmware (`davis/davis-vantage-receiver.yaml`) rather than a Python service — see "Davis Vantage Vue (ESPHome firmware)" below. All station services/firmware publish under `weatherdatalogger/` so Home Assistant (or any MQTT subscriber) gets a unified feed.

---

## Coding conventions

- **Python 3.13** is the production runtime. Code must be compatible with **3.11+ syntax** (ruff target stays `py311` — do not change it)
- **Type hints** on all public function signatures
- **stdlib only** unless a library is already in the service's `requirements.txt`; ask before adding new dependencies
- **`configparser` INI** for all runtime config — never hardcode addresses, ports, or credentials
- **`logging`** (stdlib) for all output — no `print()` in production code
- Field names in MQTT JSON payloads: **descriptive snake_case with unit suffix** (`air_temperature_c`, `station_pressure_mb`, `wind_avg_ms`, `relative_humidity_pct`)
- Each service stays as a **single self-contained file** with its own `requirements.txt`

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
weatherdatalogger/forecast-<location>/current|forecast_hourly|forecast_daily
weatherdatalogger/davis-<station_id>/<sensor>
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

Unlike Tempest/AirLink, this is **not a Python service** — it's ESPHome YAML + inline C++ lambdas (`davis/davis-vantage-receiver.yaml`) flashed to an ESP32 + CC1101 radio module. Read `davis/README.md` for hardware/wiring and CONTEXT.md's "Known Issues" section before touching this file — several non-obvious RF findings are documented there and are expensive to re-derive.

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
**Current state: `davis_rain`/`davis_rain_rate` are published *exclusively* from the Meteobridge correction handlers now — the local CC1101 tip-derived accumulation/rate calculation is disabled (commented out, not deleted) because it wasn't stable enough.** This was a deliberate architecture change once the Meteobridge corrector existed and proved consistent with the console; see "Meteobridge corrector" below for the poller itself.

- `weatherdatalogger/meteobridge/meteobridge_datalogger.py` polls a Meteobridge Pro (wired to the same ISS) every 60s (configurable) and publishes to the static control topics `weatherdatalogger/davis-vantage-receiver/set_daily_rain` / `set_rain_rate` — see `mqtt: on_message:` in the YAML. These are the *only* code paths left that call `davis_rain.publish_state()` / `davis_rain_rate.publish_state()`.
- The `set_daily_rain` handler also accepts manual corrections (e.g. `davis/scripts/set_daily_rain.sh <mm>`, installed by `deploy.sh` to `/opt/weatherdatalogger/scripts/`). Both handlers clamp to `< 500mm`(/mm-h); a rejected value is logged, not applied. Topics are intentionally static (not the dynamic `davis-<id>` prefix) since the transmitter ID auto-locks at runtime and isn't known at compile time.
- The `set_rain_rate` handler also re-anchors `rain_last_tip_ms`/`rain_tip_seen` to the correction on every call, which now serves a different purpose than originally designed: since local tip processing no longer touches these fields, they're refreshed solely by each Meteobridge poll, keeping the 60s `interval:` block's 5-minute check (see below) permanently dormant under normal operation.
- The 60s `interval:` block's rain-rate check is a **staleness safety net for Meteobridge going quiet**, not a decay mechanism for local tips anymore: since Meteobridge re-touches `rain_last_tip_ms` every ~60s (well under the 5-minute threshold), the check essentially never fires unless Meteobridge itself stops responding for 5+ minutes — in which case it still forces the rate back to `0` rather than showing a stale reading forever.
- The CC1101 tip-delta math (`ptype == 14` handler) is left in the file, fully commented out, precisely so it's a quick re-enable if Meteobridge is ever unavailable — search for "Publishing from this locally-computed accumulation/rate is DISABLED" in the YAML. `rain_count_prev` (the raw hardware tip-counter baseline) is still tracked live even while disabled, so re-enabling doesn't start from a stale baseline.
- `rain_total_mm` and `rain_count_prev` both still use `restore_value: yes` (harmless to keep — `rain_total_mm` is now written only by boot-restore and Meteobridge corrections). The local midnight-reset `on_time` trigger is also disabled (commented out) — Meteobridge/the console do their own midnight reset, so the next poll after midnight already reflects the new day.
- `esphome: on_boot:` no longer publishes anything for either rain entity — they simply sit "Unknown" for up to one Meteobridge poll interval after boot, rather than showing a restored-but-now-untrusted local value.

### Solar radiation
No sensor is fitted on this Vantage Vue ISS. The `raw == 0x3FF` "no sensor" sentinel (and later a `raw >= 1000` tolerance band) both proved unreliable against RF noise on this 10-bit field — occasional noise landed low enough to slip through as a bogus reading (e.g. raw≈1021 decoding as a fake ~1795 W/m²). Publishing is now disabled entirely in the `ptype == 5` handler; the entity correctly reads "Unavailable" in HA. Raw values are still logged at `ESP_LOGD` for reference if a real sensor is ever fitted (search for `davis_solar_radiation` to re-enable).

### Meteobridge corrector
`weatherdatalogger/meteobridge/meteobridge_datalogger.py` — a small Python service (structurally identical to `airlink_datalogger.py`: HTTP poll → parse → publish MQTT), **not** a full station integration. It has no observation topic and no database rows of its own. It started out as a periodic *correction* source on top of the CC1101's own tip-derived rain data, but the CC1101 path proved unstable and has since been disabled entirely (see "Rain accumulation & rate" above) — Meteobridge, via a Meteobridge Pro wired to the same ISS, is now the **sole** source for `davis_rain`/`davis_rain_rate`. Optional: the service logs an error and idles (doesn't crash-loop) if `[meteobridge] host` is left unconfigured. Requests use a quote-free comma-separated template (`MM_TEMPLATE = "[rain0total-daysum],[rain0rate-act]"` — `-daysum` for the accumulated-today total, `-act` for the current instantaneous rate; see the [Templates wiki](https://www.meteobridge.com/wiki/index.php?title=Templates) for the macro suffix reference), parsed as two floats — a JSON-shaped template was tried first but real hardware backslash-escaped every quote in the output (some Meteobridge firmware applies PHP/CGI-style `addslashes()`), breaking `json.loads`; the CSV format has nothing left for it to escape. Sends preemptive HTTP Basic Auth (`[meteobridge] username`/`password`, default username `meteobridge` — Meteobridge's own factory default) unless username is blank. Assumes Meteobridge is configured for metric units. See `weatherdatalogger/meteobridge/README.md`.

### Debugging this file
- Diagnostic/calibration logging used to investigate the packet-type histogram is still present but **commented out** (search `CALIBRATION (disabled)`) — uncomment to re-run the same test against different CC1101 hardware, rather than re-deriving the approach from scratch.
- A raw-packet-arrival log (`ESP_LOGD("davis", "Raw packet received: ...")`, silent at the default `INFO` level) sits right before the CRC check. Set `logger: level: DEBUG` and reflash if packets ever stop being logged, to distinguish "CC1101 isn't receiving RF frames at all" (this line never appears — hardware/RF issue) from "frames arrive but fail CRC" (this line appears but no `Packet type: ...` ever follows — decode-side issue). Revert to `INFO` afterward — `DEBUG` logs a line per packet (~every 2.5s) indefinitely otherwise.
- `esphome logs davis/davis-vantage-receiver.yaml` for remote logs requires the native API — the `api:` block in the YAML is commented out by default; uncomment it temporarily if you need this. Do **not** also add this node via Home Assistant's "ESPHome" integration UI if you do, since HA entities come from `mqtt: discovery: true` instead, and having both would duplicate every entity.
- Repeating `[I][safe_mode:142]: Boot seems successful` lines in the log are the tell for a reboot loop, even when nothing else looks wrong — check `reboot_timeout` settings (`mqtt:`, `api:`, `wifi:`) if this shows up more than once per intentional flash. A single occurrence right after a flash/reboot is normal.
- A local web dashboard is available at `http://<device-ip>/` (`web_server: port: 80`), including a diagnostic **Restart** button (`button: platform: restart`) — also discovered into HA as a diagnostic entity.

---

## Config sections

All four services (tempest, airlink, db_writer, meteobridge) share a single config file at `/opt/weatherdatalogger/config.ini`. Each service reads only the sections it needs — extra sections are ignored. The full template is `config.example.ini` at the repo root.

`client_id` is **not** in the shared config — each service's `DEFAULT_CONFIG` provides its own unique value so they don't collide on the MQTT broker.

### Shared sections (all services)

| Section | Notable keys |
|---|---|
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `qos` — `retain` is also here but `meteobridge_datalogger.py` doesn't read it (corrections are always unretained, hardcoded) |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` — not used by `meteobridge_datalogger.py`, which creates no entities of its own |

### Service-specific sections

| Service | Section | Notable keys |
|---|---|---|
| `tempest_datalogger.py` | `[udp]` | `listen_address`, `listen_port` |
| | `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |
| | `[forecast]` | `enabled`, `station_id`, `api_key`, `location`, `interval_min`, `forecast_hours` |
| `airlink_datalogger.py` | `[airlink]` | `host` (**REQUIRED**), `port` (80), `interval_s` (60), `timeout_s` (10) |
| `db_writer.py` | `[database]` | `host`, `port`, `name`, `user`, `password` (**REQUIRED**) |
| `meteobridge_datalogger.py` | `[meteobridge]` | `host` (optional — service idles if unset), `port` (80), `username` (default `meteobridge`, Meteobridge's own factory default — empty sends no `Authorization` header), `password`, `interval_s` (60), `timeout_s` (10) |

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

**Forecast discovery** publishes 9 sensors into a single "Forecast \<location\>" device:
- 7 current-condition sensors (`_FORECAST_CC_SENSORS`) — state_topic: `forecast-<loc>/current`, `value_template` extracts each field
- 2 forecast-array sensors (Hourly / Daily) — `state_topic` returns entry count via `{{ value_json | length }}`; `json_attributes_topic` points at the same topic with `json_attributes_template: "{{ {'forecasts': value_json} | tojson }}"` so the full array is available as the `forecasts` attribute

**HA does NOT support `weather` entity auto-discovery** and **`mqtt: weather:` in configuration.yaml is also invalid**. The correct approach is `template: weather:` in configuration.yaml, reading from the 9 auto-discovered sensors. The exact YAML snippet is logged at INFO the first time the forecast publishes.

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
- [x] WeatherFlow Better Forecast REST API poller — current conditions, configurable hourly depth, 10-day daily
- [x] Forecast HA discovery: 9 sensors auto-discovered; `template: weather:` YAML logged at INFO

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
- [x] ESPHome firmware (`davis/davis-vantage-receiver.yaml`) — CC1101 packet decode, CRC validation, station-ID lock
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
- [x] Manual daily-rain and rain-rate correction — publish to the static MQTT control topics `weatherdatalogger/davis-vantage-receiver/set_daily_rain` / `set_rain_rate`, or run `davis/scripts/set_daily_rain.sh <mm>` (installed by `deploy.sh` to `/opt/weatherdatalogger/scripts/`).
- [x] Solar radiation publishing disabled entirely — no sensor is fitted on this Vue, and RF noise on the 10-bit field made every "no sensor" sentinel check tried (exact `raw == 0x3FF` match, then a `raw >= 1000` tolerance band) unreliable enough that occasional garbage still got published as a fake reading. Entity now correctly reads "Unavailable"; raw values still logged at DEBUG for reference.
- [x] Diagnostic "Restart" button (`button: platform: restart`) — available on the local web UI (`web_server: port: 80`) and as a diagnostic entity in HA.

### Meteobridge corrector
- [x] New service `weatherdatalogger/meteobridge/meteobridge_datalogger.py` — polls a Meteobridge Pro's REST template API (proven consistent with the console) and republishes rain_today/rain_rate as corrections to the Davis receiver's own MQTT control topics, on a configurable interval (default 60s). Not a full station integration — no observation topic, no database rows.
- [x] Promoted to the **sole** source for `davis_rain`/`davis_rain_rate` — the CC1101 tip-derived rain accumulation/rate calculation is now disabled (commented out, not deleted, for easy re-enable) since it wasn't stable enough; see "Rain accumulation & rate" above.
- [x] Optional service — logs an error and idles (doesn't crash-loop) if `[meteobridge] host` is left unconfigured
- [x] Full service scaffold: `config.example.ini`, `requirements.txt`, `systemd/meteobridge-datalogger.service`, `README.md` — structurally mirrors `airlink/` exactly
- [x] `[meteobridge]` section added to the shared `weatherdatalogger/config.example.ini`

### Infrastructure
- [x] Top-level deploy script (`scripts/deploy.sh`) — staging clone, installs all four services under `/opt/weatherdatalogger/`, applies DB migrations, updates all venvs, restarts enabled services
- [x] `systemctl status` in deploy uses `--lines=20 || true` — avoids hanging and tolerates services still in "activating" state
- [x] Single shared config at `/opt/weatherdatalogger/config.ini` — all services read from one file; auto-generates `db.cnf` for MySQL client
- [x] Ruff linting (`scripts/lint`, `.ruff.toml`)
- [x] `deploy.sh` also installs `davis/scripts/set_daily_rain.sh` to `/opt/weatherdatalogger/scripts/` — `davis/` sits at the repo root as a sibling of `weatherdatalogger/`, not inside it, so this needed an explicit install step (`$STAGING/davis/...`, not `$STAGING_WDL/...`) even though the Davis ESPHome firmware itself is flashed independently and isn't otherwise part of the server deploy

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
