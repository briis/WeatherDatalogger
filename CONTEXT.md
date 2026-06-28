# WeatherDatalogger — Project Context

## Goal

A unified weather data pipeline that collects data from **two different weather station brands** and publishes everything to a single MQTT broker under a common topic namespace. Downstream consumers (Home Assistant, databases, dashboards, etc.) subscribe to MQTT and are completely decoupled from the hardware.

---

## MQTT Topic Structure

```
weatherdatalogger/
  tempest-<serial>/        ← WeatherFlow Tempest (this repo, Python service)
    observation            — full obs_st payload (raw + derived metrics)
    rapid_wind
    rain_start
    lightning
    device_status
    hub_status
  davis-<id>/              ← Davis Vantage Vue (ESPHome firmware, separate project)
    <sensor topics>
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
- Receiver: **ESP32 + CC1101** (868.35 MHz, CRC-16/CCITT, 5 EU hop channels)
- ESP32 runs **ESPHome** firmware which handles RF reception and MQTT publishing
- **Status: deferred — hardware not yet available**

---

## Repository Structure (actual, flat layout)

```
tempest-weatherdatalogger/
├── tempest_datalogger.py       ← Main Python service (UDP → MQTT, single file)
├── config.example.ini          ← Documented template for all config keys
├── config.dev.ini              ← Dev container config (local mosquitto)
├── config.ini                  ← Production config (gitignored, credentials)
├── requirements.txt            ← Runtime dependency: paho-mqtt
├── requirements-dev.txt        ← Dev/lint tools: ruff
├── .ruff.toml                  ← Ruff linter config (target-version = "py311")
├── scripts/
│   ├── deploy.sh               ← Pull from GitHub, update deps, restart service
│   ├── lint                    ← ruff format + ruff check --fix
│   └── simulate_udp.py         ← Sends all 6 Tempest message types to localhost
├── systemd/
│   └── tempest-datalogger.service  ← systemd unit for Debian LXC
├── CONTEXT.md                  ← This file
└── AGENT.md                    ← Instructions for AI coding assistants
```

---

## Deployment Environment

- **Proxmox** hypervisor running **Debian Bookworm LXC containers**
- Tempest datalogger runs as a Python 3.11 service inside an LXC
- Runs as a dedicated unprivileged user (`tempest`) under systemd
- No Docker, no virtualenv wrappers — direct venv at `/opt/tempest-datalogger/venv`
- Deploy with `sudo bash scripts/deploy.sh`
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

---

## Config Sections

| Section | Key settings |
|---|---|
| `[udp]` | `listen_address`, `listen_port` |
| `[mqtt]` | `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `client_id`, `retain`, `qos` |
| `[logging]` | `level`, `file` |
| `[homeassistant]` | `discovery` (bool), `discovery_prefix` |
| `[station]` | `elevation_m`, `height_above_ground_m`, `data_dir` |

`data_dir` (default: empty = same directory as config file) controls where the two persistence files are written:
- `tempest_lightning.json` — rolling 24h lightning event log
- `tempest_pressure.json` — rolling 24h pressure history for trend calculation

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
- **Forecast \<location\>** device — 7 current-condition sensors (condition, temperature, humidity, wind speed, wind bearing, pressure, dew point)

Discovery is published once per device per run (tracked with an in-memory set). The `lightning_last_detected` sensor uses `device_class: timestamp` so HA displays it natively as "2 hours ago".

> **Note:** HA MQTT integration does not support auto-discovery for `weather` entities (only `sensor`, `binary_sensor`, switch, etc. are discoverable). To create a full weather card with hourly/daily forecast, add a `mqtt: weather:` block to `configuration.yaml` — the exact YAML is logged at INFO level the first time the forecast is published.

---

## Conventions

- Python: 3.11+, type hints on all public functions
- Linting: ruff (`scripts/lint`), `select = ["ALL"]`, `target-version = "py311"`
- Logging: stdlib `logging`, level configurable in `config.ini`
- Config: `configparser` INI format
- Units: always SI in MQTT payloads; label field names with unit suffix
- MQTT QoS: default 0 (configurable), retain: default false (state topics), always true (HA discovery)
