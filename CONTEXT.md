# WeatherDatalogger — Project Context

## Goal

A unified weather data pipeline that collects data from **two different weather station brands** and publishes everything to a single MQTT broker under a common topic namespace. Downstream consumers (Home Assistant, databases, dashboards, etc.) subscribe to MQTT and are completely decoupled from the hardware.

---

## MQTT Topic Structure

```
weatherdatalogger/
  tempest-<serial>/        ← WeatherFlow Tempest (this repo, Python)
    observation
    rapid_wind
    rain_start
    lightning
    device_status
    hub_status
  davis-<id>/              ← Davis Vantage Vue (ESPHome firmware, separate)
    <sensor topics>
```

`<serial>` for Tempest comes from the hub's broadcast (`ST-…` for the sensor, `HB-…` for the hub).
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
- CC1101 module: GERUI 3-pack 868 MHz with antenna

---

## Repository Structure (intended)

```
weatherdatalogger/
├── tempest/
│   ├── tempest_datalogger.py   ← Main Python service (UDP → MQTT)
│   ├── config.ini              ← Runtime configuration
│   └── requirements.txt        ← Python dependencies (paho-mqtt)
├── davis/
│   └── davis-vantage-receiver.yaml  ← ESPHome firmware config
├── systemd/
│   └── tempest-datalogger.service   ← systemd unit for Debian/LXC
├── CONTEXT.md                  ← This file
├── AGENT.md                    ← Instructions for AI coding assistants
└── README.md
```

---

## Deployment Environment

- **Proxmox** hypervisor running **Debian-based LXC containers**
- Tempest datalogger runs as a Python service inside an LXC
- Davis receiver runs standalone on an ESP32 (ESPHome OTA updates)
- MQTT broker (e.g. Mosquitto) runs separately — address configured in `config.ini`

---

## Tempest Datalogger — Key Design Decisions

- Pure Python, single file (`tempest_datalogger.py`), no frameworks
- Only external dependency: `paho-mqtt`
- Config via INI file (not env vars or CLI flags), path passed with `--config`
- UDP socket binds `0.0.0.0:50222`, receives all hub broadcasts
- Auto-reconnects to MQTT on disconnect (uses `loop_start()` thread)
- Each UDP message type maps to its own MQTT subtopic
- Payload fields use descriptive names with units as suffix (`_ms`, `_mb`, `_c`, `_pct`, etc.)
- Runs as a dedicated `tempest` system user under systemd

---

## UDP Message Types (Tempest)

| Type            | MQTT subtopic    | Key fields                                              |
|-----------------|------------------|---------------------------------------------------------|
| `obs_st`        | `observation`    | wind, pressure, temp, humidity, UV, solar, rain, lightning, battery |
| `rapid_wind`    | `rapid_wind`     | wind speed + direction, every ~3 s                     |
| `evt_precip`    | `rain_start`     | timestamp only (event trigger)                          |
| `evt_strike`    | `lightning`      | distance_km, energy                                     |
| `device_status` | `device_status`  | voltage, RSSI, sensor_status bitmask, uptime            |
| `hub_status`    | `hub_status`     | firmware, uptime, radio_status, reset_flags             |

---

## Conventions

- Python: 3.10+, type hints encouraged, no external frameworks
- Logging: stdlib `logging`, level configurable in `config.ini`
- Config: `configparser` INI format, `config.ini` co-located with the script
- Units: always SI in MQTT payloads; label field names with unit suffix
- MQTT QoS: default 0 (configurable), retain: default false (configurable)
