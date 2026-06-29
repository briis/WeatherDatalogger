# AGENT.md — Instructions for AI Coding Assistants

This file gives AI assistants (Claude Code, Copilot, Cursor, etc.) the context
needed to contribute to this project effectively. Read CONTEXT.md first for the
full architecture overview.

---

## What this project is

A weather data pipeline with two active Python services:

1. **Tempest datalogger** (`tempest/tempest_datalogger.py`) — receives WeatherFlow Tempest UDP broadcasts, computes derived metrics, and publishes everything to MQTT
2. **DB writer** (`database/db_writer.py`) — subscribes to MQTT observation topics and persists readings to MariaDB (`realtime` + `history` tables)

A future component will handle Davis Vantage Vue via ESP32 + CC1101. Both station services publish under `weatherdatalogger/` so Home Assistant (or any MQTT subscriber) gets a unified feed.

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
1. Add a migration file `database/migrations/YYYYMMDD_add_<field>.sql` with `ALTER TABLE realtime ADD COLUMN …` and `ALTER TABLE history ADD COLUMN …`
2. Add the field name to `_OBS_FIELDS` in `db_writer.py` (if it maps 1:1 from the payload) or handle it in `_payload_to_row()` (if it needs conversion, like `lightning_last_detected`)
3. The SQL column lists (`_COL_LIST`, `_PLACEHOLDERS`, `_UPDATE_CLAUSE`) are built from `_ALL_COLS` at import time — no further changes needed

### DB connection management
- `DbWriter._execute()` retries once on `OperationalError` (lost connection), reconnecting via `_connect()` before the second attempt
- `autocommit=True` — no explicit transaction management needed for single-statement writes
- `_known_stations` is an in-memory set; it is rebuilt if the process restarts (safe — `INSERT IGNORE` is idempotent)

---

## Config sections

### tempest_datalogger.py

| Section | Notable keys |
|---|---|
| `[udp]` | `listen_address`, `listen_port` |
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `retain`, `qos` |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` |
| `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |
| `[forecast]` | `enabled`, `station_id`, `api_key`, `location`, `interval_min`, `forecast_hours` (default 48) |

`data_dir` is where `tempest_lightning.json` and `tempest_pressure.json` are written.
Default (empty) = directory of the config file.

### db_writer.py

| Section | Notable keys |
|---|---|
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `client_id` |
| `[database]` | `host`, `port`, `name`, `user`, `password` |
| `[logging]` | `level`, `file` |

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
- [x] `stations`, `realtime`, `history`, `schema_migrations` tables
- [x] DB writer service (`database/db_writer.py`) subscribing to `weatherdatalogger/+/observation`
- [x] Auto-registration of new stations on first observation
- [x] Upsert into `realtime`; append into `history` on every message
- [x] systemd service unit (`database/systemd/weatherdb-writer.service`)
- [x] Migration system: numbered SQL files in `database/migrations/`, tracked in `schema_migrations`

### Infrastructure
- [x] Top-level deploy script (`scripts/deploy.sh`) — staging clone, installs both services, applies DB migrations, updates both venvs, restarts services
- [x] Ruff linting (`scripts/lint`, `.ruff.toml`)

## What's next / TODO

- [ ] **Davis Vantage Vue** — ESPHome firmware written (`davis/davis-vantage-receiver.yaml`), hardware available; needs field testing and DB schema additions (e.g. `battery_low` column)
- [ ] Dashboard / charting — Grafana or similar consuming MariaDB `history` table
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
