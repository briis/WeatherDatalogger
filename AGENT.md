# AGENT.md — Instructions for AI Coding Assistants

This file gives AI assistants (Claude Code, Copilot, Cursor, etc.) the context
needed to contribute to this project effectively. Read CONTEXT.md first for the
full architecture overview.

---

## What this project is

A weather data pipeline with two independent collectors that both publish to the
same MQTT broker under `weatherdatalogger/`. One collector is a Python service
(Tempest UDP listener), the other is ESPHome firmware (Davis RF receiver). This
repo contains both.

---

## Coding conventions

- **Python 3.14+** — use modern syntax (`match`, union types with `|`, etc.)
- **Type hints** on all function signatures
- **stdlib only** unless a library is already in `requirements.txt`; ask before adding new dependencies
- **`configparser` INI** for all runtime config — never hardcode addresses, ports, or credentials
- **`logging`** (stdlib) for all output — no `print()` statements in production code
- Field names in MQTT JSON payloads use **descriptive snake_case with unit suffix**: `air_temperature_c`, `station_pressure_mb`, `wind_avg_ms`, `relative_humidity_pct`
- Keep the main service file (`tempest_datalogger.py`) as a **single self-contained file** — it runs inside a minimal Debian LXC

---

## MQTT topic rules — follow these exactly

```
weatherdatalogger/tempest-<serial>/<message_type>
weatherdatalogger/davis-<station_id>/<sensor>
```

- `<serial>` comes from the `serial_number` field in the UDP broadcast (e.g. `ST-00000512`, `HB-00013030`)
- Do **not** normalise or strip the prefix letters from serials
- Subtopic names are lowercase with underscores
- Never publish to the bare `weatherdatalogger/` topic itself

---

## Tempest datalogger (`tempest/tempest_datalogger.py`)

### How it works
1. Binds a UDP socket on `0.0.0.0:50222`
2. Receives JSON broadcast packets from the Tempest Hub
3. Routes each packet by its `type` field to the appropriate parser function
4. Publishes the parsed flat dict as JSON to MQTT

### Parser functions
Each message type has a dedicated `parse_<type>()` function that returns a flat
dict or `None` on failure. Adding a new message type means:
1. Write a `parse_<type>()` function
2. Add an entry to the `PARSERS` dict: `"type_string": ("subtopic", parse_fn)`

### MQTT client
- Uses `paho.mqtt.client` with `loop_start()` (background thread)
- Auto-reconnects via `on_disconnect` callback + `mqtt_connect()` retry loop
- Config keys: `broker`, `port`, `username`, `password`, `tls`, `base_topic`, `client_id`, `retain`, `qos`

---

## Davis receiver (`davis/davis-vantage-receiver.yaml`)

- ESPHome YAML for an **ESP32 + CC1101** (868.35 MHz)
- Handles RF reception, CRC validation, and MQTT publishing
- Station ID auto-locks on first valid packet
- Do not change the frequency or bandwidth without checking the EU hop channel plan

---

## Deployment target

- **Debian Bookworm LXC** on Proxmox
- Python service managed by **systemd** (unit file in `systemd/`)
- Runs as a dedicated unprivileged user (`tempest`)
- No Docker, no virtualenv wrappers in production — direct venv at `/opt/tempest-datalogger/venv`
- The LXC must be on the **same L2 network segment** as the Tempest Hub (UDP broadcast does not cross routed boundaries)

---

## What's already done ✅

- [x] Tempest UDP listener with all 6 message type parsers
- [x] MQTT publish with configurable base topic, QoS, retain, TLS
- [x] INI-based config with documented defaults
- [x] systemd service unit
- [x] ESPHome YAML for Davis CC1101 receiver (separate, in `davis/`)

## What's next / TODO

- [ ] `requirements.txt` for the tempest service (`paho-mqtt>=1.6`)
- [ ] Davis MQTT topic structure — align with `weatherdatalogger/davis-<id>/` scheme
- [ ] Decide on and document derived fields (dew point, feels-like, etc.) — compute in datalogger or leave to consumers?
- [ ] Unit tests for the parser functions (no network required, just dicts)
- [ ] Health/watchdog topic: `weatherdatalogger/tempest-<serial>/status` with `online`/`offline` and last-seen timestamp
- [ ] Optional: Home Assistant MQTT discovery payloads

---

## Things to avoid

- Do not introduce async frameworks (asyncio, trio) without discussion — the current threading model (UDP main thread + MQTT background thread) is intentional and simple
- Do not add a web server, REST API, or database to the Tempest logger — MQTT is the only output
- Do not change the MQTT topic structure without updating both this file and CONTEXT.md
- Do not store secrets in code or config files committed to the repo — use a `.env` file or environment variables for credentials if needed in CI
