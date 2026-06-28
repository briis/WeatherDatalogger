# AGENT.md — Instructions for AI Coding Assistants

This file gives AI assistants (Claude Code, Copilot, Cursor, etc.) the context
needed to contribute to this project effectively. Read CONTEXT.md first for the
full architecture overview.

---

## What this project is

A weather data pipeline. The main component is a Python service that receives
WeatherFlow Tempest UDP broadcasts and publishes them (plus computed derived
metrics) to MQTT. A future component will do the same for Davis Vantage Vue via
ESP32 + CC1101. Both publish under `weatherdatalogger/` so Home Assistant (or
any MQTT subscriber) gets a unified feed.

---

## Coding conventions

- **Python 3.11** — the production LXC runs Python 3.11. Do not use syntax that
  requires 3.12+ (e.g. `type` aliases, newer `match` features).
- **Type hints** on all public function signatures
- **stdlib only** unless a library is already in `requirements.txt`; ask before
  adding new dependencies
- **`configparser` INI** for all runtime config — never hardcode addresses,
  ports, or credentials
- **`logging`** (stdlib) for all output — no `print()` in production code
- Field names in MQTT JSON payloads: **descriptive snake_case with unit suffix**
  (`air_temperature_c`, `station_pressure_mb`, `wind_avg_ms`, `relative_humidity_pct`)
- Keep `tempest_datalogger.py` as a **single self-contained file**

---

## Critical: ruff target-version must stay "py311"

`.ruff.toml` has `target-version = "py311"`. **Do not change this.**

If set to `py314`, ruff will reformat `except (E1, E2):` → `except E1, E2:`
(PEP 758 syntax valid in 3.14 but a `SyntaxError` in 3.11). This has broken
production before. Always run `scripts/lint` after editing and check that
`except` clauses keep their parentheses.

---

## MQTT topic rules — follow these exactly

```
weatherdatalogger/tempest-<serial>/<message_type>
weatherdatalogger/davis-<station_id>/<sensor>
```

- `<serial>` comes from the `serial_number` field in the UDP broadcast
  (`ST-00209955`, `HB-00013030`, etc.) with `:` replaced by `-`
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
1. Write a `parse_<type>(msg: dict) -> dict | None` function
2. Add an entry to `PARSERS`: `"type_string": ("subtopic_name", parse_fn)`
3. If it needs HA discovery, add sensor tuples to the appropriate `_*_SENSORS` list
   and register it in `_HA_DISCOVERY_MAP`

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

## Config sections

| Section | Notable keys |
|---|---|
| `[udp]` | `listen_address`, `listen_port` |
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `retain`, `qos` |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` |
| `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |
| `[forecast]` | `enabled`, `station_id`, `api_key`, `location`, `interval_min`, `forecast_hours` (default 48), unit keys |

`data_dir` is where `tempest_lightning.json` and `tempest_pressure.json` are written.
Default (empty) = directory of the config file.

`forecast_hours` slices `fcast["hourly"]` before passing to `_parse_hourly_forecast` — no change needed to the parser.

---

## MQTT client

- Uses `paho.mqtt.client` with `loop_start()` (background thread)
- Auto-reconnects via `on_disconnect` callback + `mqtt_connect()` retry loop
- State topic messages: `retain` from config (should be `true` for HA)
- HA discovery config messages: always `retain=True, qos=1`

---

## HA discovery

- One retained config message per sensor to `<prefix>/sensor/<unique_id>/config`
- Published once per device per process run (tracked by `_discovered` set)
- Device info (`_device_info()`) distinguishes hub (`HB-`) from sensor (`ST-`)
- `_HA_DISCOVERY_MAP` maps UDP type → (subtopic, sensor_list)
- **HA does NOT support `weather` entity discovery** — only `sensor` and a few
  other entity types work with MQTT discovery. Forecast current-conditions are
  exposed as individual sensors (`_FORECAST_CC_SENSORS`). A YAML snippet for a
  `mqtt: weather:` entity (for a weather card + hourly/daily forecast) is logged
  at INFO the first time the forecast publishes.

---

## Dev environment

The devcontainer cannot receive real Tempest UDP broadcasts (Docker Desktop on
macOS runs in a Linux VM; LAN broadcasts never reach it). Use the simulator:

```bash
python3 scripts/simulate_udp.py          # sends all 6 message types once
python3 scripts/simulate_udp.py --count 0 --interval 60  # continuous, every 60s
```

Subscribe to verify output:
```bash
mosquitto_sub -h localhost -t 'weatherdatalogger/#' -v
```

Run the datalogger:
```bash
python3 tempest_datalogger.py --config config.dev.ini
```

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

- [x] Tempest UDP listener with all 6 message type parsers
- [x] MQTT publish with configurable base topic, QoS, retain, TLS
- [x] INI-based config with documented defaults (`config.example.ini`)
- [x] Dev config for devcontainer (`config.dev.ini`)
- [x] systemd service unit (`systemd/tempest-datalogger.service`)
- [x] Deploy script (`scripts/deploy.sh`)
- [x] UDP packet simulator (`scripts/simulate_udp.py`)
- [x] Ruff linting (`scripts/lint`, `.ruff.toml`)
- [x] Home Assistant MQTT discovery (all raw + derived sensors auto-discovered)
- [x] Derived metrics: dew point, wet bulb, delta T, feels like, heat index,
      wind chill, vapor pressure, air density, rain rate, sea level pressure
- [x] Station pressure trend (3h, persisted across restarts)
- [x] Sea level pressure trend (3h, persisted across restarts)
- [x] Lightning history: last detected timestamp, 3h count, 3h min/max distance
      (persisted across restarts in `tempest_lightning.json`)
- [x] WeatherFlow Better Forecast REST API poller (background daemon thread)
      — current conditions, hourly (configurable depth via `forecast_hours`),
      10-day daily — published to `forecast-<location>/` MQTT topics
- [x] Forecast HA discovery: 7 current-condition sensors auto-discovered;
      YAML snippet for `mqtt: weather:` entity logged at INFO on first run

## What's next / TODO

- [ ] **Davis Vantage Vue** — deferred until ESP32 + CC1101 hardware arrives
- [ ] Unit tests for parser functions (no network required, just dicts in / dict out)
- [ ] Health/watchdog topic: `weatherdatalogger/tempest-<serial>/status` with
      `online`/`offline` LWT and last-seen timestamp
- [ ] Clean-up deploy script, so we only copy files that are need for the production environment

---

## Things to avoid

- Do not introduce async frameworks (asyncio, trio) — the current threading model
  (UDP main thread + MQTT background thread) is intentional and simple
- Do not add a web server, REST API, or database — MQTT is the only output
- Do not change the MQTT topic structure without updating CONTEXT.md and
  the HA discovery sensor list
- Do not store secrets in committed files — `config.ini` is gitignored
- Do not bump `target-version` in `.ruff.toml` past `py311` without verifying
  the production Python version first
