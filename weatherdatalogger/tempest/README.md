# WeatherFlow Tempest UDP → MQTT Datalogger

Listens for UDP broadcasts from a **WeatherFlow Tempest hub** on the local network (port 50222), computes derived weather metrics, and publishes everything as JSON to an MQTT broker.

Designed to run as a **systemd service on Debian/Proxmox LXC** and integrate with **Home Assistant** via MQTT auto-discovery.

> **Installation:** Follow the [server installation guide](../README.md#installation-debian--proxmox-lxc) first, then return here to configure the Tempest datalogger.

---

## Features

- Receives all 6 Tempest UDP message types and publishes them to individual MQTT topics
- Computes derived metrics on every observation: dew point, wet bulb, delta-T, heat index, wind chill, feels like, vapor pressure, air density, rain rate, sea level pressure
- Station and sea level pressure trend (Rising / Steady / Falling) with 3-hour history — persisted across restarts
- Lightning history: last-detected timestamp, 3-hour count, closest/farthest distance — persisted across restarts
- Home Assistant MQTT auto-discovery for all sensors
- Systemd service with automatic restart and journald logging

> **Forecast data** used to be fetched here from the WeatherFlow Better Forecast API — it's now handled by the separate [`weatherdatalogger/visualcrossing/`](../visualcrossing/) service instead (Visual Crossing, not tied to a WeatherFlow station). See that service's README.

---

## Topic Structure

### Tempest sensor data

```
weatherdatalogger/tempest-<serial>/<subtopic>
```

| Subtopic | Source | Content |
|---|---|---|
| `observation` | ST-… sensor | Full observation + all derived metrics |
| `rapid_wind` | ST-… sensor | Wind speed and direction, every ~3 s |
| `rain_start` | ST-… sensor | Precipitation start event |
| `lightning` | ST-… sensor | Lightning strike: distance and energy |
| `device_status` | ST-… sensor | Voltage, RSSI, sensor status, uptime |
| `hub_status` | HB-… hub | Firmware, uptime, radio stats |

Example:
```
weatherdatalogger/tempest-ST-00000512/observation
weatherdatalogger/tempest-HB-00013030/hub_status
```

---

## Setup

After completing the [server installation](../README.md#installation-debian--proxmox-lxc), edit the shared config file:

```bash
nano /opt/weatherdatalogger/config.ini
```

**Required before first start** — this service is off by default:

| Key | Section | What to set |
|---|---|---|
| `enabled` | `[tempest]` | `true` |
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |

```ini
[tempest]
enabled = true          # required — this service is off by default

[mqtt]
broker = 192.168.1.10   # IP or hostname of your MQTT broker
retain = true           # recommended for Home Assistant

[homeassistant]
discovery = true        # auto-create HA devices and sensors

[station]
elevation_m = 42        # your station elevation above sea level in metres
```

Enable and start the service:

```bash
systemctl enable --now tempest-datalogger
```

Verify:

```bash
systemctl status tempest-datalogger
journalctl -u tempest-datalogger -f
```

You should see:

```
2024-06-28 08:00:01  INFO  Listening for Tempest UDP broadcasts on 0.0.0.0:50222
2024-06-28 08:00:07  INFO  obs_st → weatherdatalogger/tempest-ST-00000512/observation
```

---

## Configuration

All settings live in `config.ini` (copied from `config.example.ini`). Every key has a built-in default — only change what you need.

| Section | Key | Default | Description |
|---|---|---|---|
| `[tempest]` | `enabled` | `false` | Set `true` to run this service — off by default so a fresh install doesn't try to log a station you don't own |
| `[udp]` | `listen_address` | `0.0.0.0` | Interface to bind |
| `[udp]` | `listen_port` | `50222` | Tempest hub broadcast port |
| `[mqtt]` | `broker` | `localhost` | MQTT broker hostname or IP |
| `[mqtt]` | `port` | `1883` | MQTT broker port |
| `[mqtt]` | `username` | _(empty)_ | MQTT username |
| `[mqtt]` | `password` | _(empty)_ | MQTT password |
| `[mqtt]` | `tls` | `false` | Enable TLS/SSL |
| `[mqtt]` | `base_topic` | `weatherdatalogger` | Root MQTT topic prefix |
| `[mqtt]` | `retain` | `false` | Retain state messages — set `true` for Home Assistant |
| `[mqtt]` | `qos` | `0` | MQTT QoS level (0/1/2) |
| `[logging]` | `level` | `INFO` | Log level: `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `[logging]` | `file` | _(empty)_ | Optional log file path (empty = stdout/journal only) |
| `[homeassistant]` | `discovery` | `false` | Publish MQTT discovery messages for Home Assistant |
| `[homeassistant]` | `discovery_prefix` | `homeassistant` | Must match HA's `discovery_prefix` setting |
| `[station]` | `elevation_m` | `0` | Station elevation above sea level (metres) — needed for sea level pressure |
| `[station]` | `height_above_ground_m` | `0` | Sensor height above ground (metres) |
| `[station]` | `data_dir` | _(empty)_ | Directory for persistence files; empty = same folder as `config.ini` |

---

## Home Assistant Integration

### Sensor auto-discovery

With `discovery = true` in `[homeassistant]` and `retain = true` in `[mqtt]`, the service publishes retained MQTT discovery messages and Home Assistant automatically creates:

- **Tempest ST-xxxxx** — all raw observation fields and derived metrics
- **Tempest HB-xxxxx** — hub status sensors

For a forecast/weather entity, see [`weatherdatalogger/visualcrossing/`](../visualcrossing/).

---

## Verifying MQTT Output

```bash
mosquitto_sub -h <broker> -t "weatherdatalogger/#" -v
```

### Example `observation` payload

```json
{
  "timestamp": 1720000000,
  "wind_lull_ms": 0.5,
  "wind_avg_ms": 1.2,
  "wind_gust_ms": 2.1,
  "wind_direction_deg": 220,
  "station_pressure_mb": 1013.2,
  "air_temperature_c": 18.5,
  "relative_humidity_pct": 65.0,
  "illuminance_lux": 42000,
  "uv_index": 3.2,
  "solar_radiation_wm2": 320,
  "rain_accumulation_mm": 0.0,
  "battery_volts": 2.81,
  "serial_number": "ST-00000512",
  "hub_sn": "HB-00013030",
  "dew_point_c": 11.8,
  "wet_bulb_c": 14.2,
  "delta_t_c": 4.3,
  "heat_index_c": 18.5,
  "wind_chill_c": 18.5,
  "feels_like_c": 18.5,
  "vapor_pressure_mb": 13.6,
  "air_density_kgm3": 1.213,
  "rain_rate_mmh": 0.0,
  "sea_level_pressure_mb": 1015.8,
  "pressure_trend_mb": 0.4,
  "pressure_trend": "Steady",
  "sea_level_pressure_trend_mb": 0.4,
  "sea_level_pressure_trend": "Steady",
  "lightning_last_detected": null,
  "lightning_count_3h": 0,
  "lightning_min_dist_3h_km": null,
  "lightning_max_dist_3h_km": null
}
```

---

## Troubleshooting

| Problem | Check |
|---|---|
| No UDP packets received | Hub and LXC must be on the **same L2 network** — UDP broadcasts do not cross VLANs or routed segments. Check the Proxmox bridge/VLAN config. |
| MQTT connect failed | Verify `broker` and `port` in `config.ini`. Check firewall rules on the broker host. |
| HA does not discover sensors | Ensure `discovery = true` and `retain = true`. Restart the service. Verify `discovery_prefix` matches HA's setting (default `homeassistant`). |
| Sea level pressure seems wrong | Set `elevation_m` in `[station]` to your actual elevation above sea level in metres. |
| Pressure trend is `null` | Normal until 3 hours of history have accumulated. The history is persisted in `tempest_pressure.json` so it survives restarts. |
| Lightning history resets on restart | Check that `data_dir` (or the config file directory) is writable by the `tempest` user and that `tempest_lightning.json` exists. |
| No data after hub reboot | The hub re-announces within ~60 s — wait and check logs. |
