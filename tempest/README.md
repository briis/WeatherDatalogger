# WeatherFlow Tempest UDP → MQTT Datalogger

Listens for UDP broadcasts from a **WeatherFlow Tempest hub** on the local network (port 50222), computes derived weather metrics, and publishes everything as JSON to an MQTT broker. Optionally polls the WeatherFlow REST API to publish hourly and daily forecast data.

Designed to run as a **systemd service on Debian/Proxmox LXC** and integrate with **Home Assistant** via MQTT auto-discovery.

---

## Features

- Receives all 6 Tempest UDP message types and publishes them to individual MQTT topics
- Computes derived metrics on every observation: dew point, wet bulb, delta-T, heat index, wind chill, feels like, vapor pressure, air density, rain rate, sea level pressure
- Station and sea level pressure trend (Rising / Steady / Falling) with 3-hour history — persisted across restarts
- Lightning history: last-detected timestamp, 3-hour count, closest/farthest distance — persisted across restarts
- Home Assistant MQTT auto-discovery for all sensors (Tempest + Forecast devices)
- Optional WeatherFlow Better Forecast REST API poller — current conditions plus configurable hourly (default 48 h, up to 120 h) and 10-day daily forecast
- Systemd service with automatic restart and journald logging

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

### WeatherFlow Forecast (optional)

```
weatherdatalogger/forecast-<location>/<subtopic>
```

| Subtopic | Content |
|---|---|
| `current` | Current conditions: condition, temperature, humidity, wind, pressure, dew point |
| `forecast_hourly` | Hourly forecast JSON array (up to `forecast_hours` entries, default 48) |
| `forecast_daily` | Daily forecast JSON array (up to 10 days) |

---

## Requirements

- Python 3.11
- `paho-mqtt` (see `requirements.txt`)
- MQTT broker (e.g. Mosquitto)
- The LXC/host must be on the **same L2 network segment** as the Tempest Hub — UDP broadcasts do not cross routed boundaries or VLANs

---

## Installation (Debian / Proxmox LXC)

### 1. Install prerequisites

```bash
apt update && apt install -y python3.11 python3.11-venv git mariadb-server
```

On Debian, MariaDB is already secured by default — root access requires no password and is restricted to the system `root` user via Unix socket authentication.

### 2. Create a dedicated service user

```bash
useradd -r -s /usr/sbin/nologin tempest
```

### 3. Create the install directory and bootstrap the deploy script

Clone the repo temporarily to get the deploy script onto disk (SSH key required):

```bash
git clone --depth 1 git@github.com:briis/WeatherDatalogger.git /tmp/wdl-bootstrap
mkdir -p /opt/tempest-datalogger/scripts
cp /tmp/wdl-bootstrap/scripts/deploy.sh /opt/tempest-datalogger/scripts/deploy.sh
chmod +x /opt/tempest-datalogger/scripts/deploy.sh
rm -rf /tmp/wdl-bootstrap
```

> Once the repository is made public you can replace the above with a single `curl` command. For now, SSH access is required because the repo is private.

### 4. Run the deploy script (first time)

```bash
sudo bash /opt/tempest-datalogger/scripts/deploy.sh
```

This fetches only the production files from GitHub, installs the SQL scripts under `/opt/tempest-datalogger/database/`, creates the Python virtual environment, installs dependencies, and installs the systemd unit file. Database migrations are skipped on this first run because the credentials file does not exist yet.

### 5. Configure MariaDB for network access

By default MariaDB on Debian binds to `127.0.0.1` only. Change it to listen on all interfaces so other hosts on the network can connect:

```bash
sed -i 's/^bind-address\s*=.*/bind-address = 0.0.0.0/' /etc/mysql/mariadb.conf.d/50-server.cnf
systemctl restart mariadb
```

Verify it is listening on all interfaces:

```bash
ss -tlnp | grep 3306
```

You should see `0.0.0.0:3306` in the output.

### 6. Create the database

Edit the password in the SQL script, then create the database and application user:

```bash
nano /opt/tempest-datalogger/database/01_create_database.sql
mariadb -u root < /opt/tempest-datalogger/database/01_create_database.sql
```

### 7. Store database credentials

```bash
mkdir -p /etc/weatherdatalogger
cat > /etc/weatherdatalogger/db.cnf <<'EOF'
[client]
host     = localhost
database = weatherdatalogger
user     = weatherlogger
password = your_password_here
EOF
chmod 600 /etc/weatherdatalogger/db.cnf
```

### 8. Create the tables

```bash
mariadb --defaults-extra-file=/etc/weatherdatalogger/db.cnf \
    < /opt/tempest-datalogger/database/02_create_tables.sql
```

### 9. Configure

```bash
cp /opt/tempest-datalogger/config.example.ini /opt/tempest-datalogger/config.ini
nano /opt/tempest-datalogger/config.ini
```

Minimum required settings:

```ini
[mqtt]
broker = 192.168.1.10   # IP or hostname of your MQTT broker
retain = true           # recommended for Home Assistant

[homeassistant]
discovery = true        # auto-create HA devices and sensors

[station]
elevation_m = 42        # your station elevation above sea level in metres
```

See [Configuration](#configuration) for all available options.

### 10. Enable and start the service

```bash
systemctl enable --now tempest-datalogger
```

### 11. Verify

```bash
systemctl status tempest-datalogger
journalctl -u tempest-datalogger -f
```

You should see lines like:

```
2024-06-28 08:00:01  INFO      Listening for Tempest UDP broadcasts on 0.0.0.0:50222
2024-06-28 08:00:07  INFO      obs_st → weatherdatalogger/tempest-ST-00000512/observation
```

---

## Updating

```bash
sudo bash /opt/tempest-datalogger/scripts/deploy.sh
```

The script clones the latest code to a temporary staging directory, copies only the files needed for production, syncs the systemd unit if it changed, updates Python dependencies, restores ownership to the `tempest` user, and restarts the service.

Files installed to `/opt/tempest-datalogger`:
- `tempest_datalogger.py` — the service
- `requirements.txt` — Python dependencies
- `config.example.ini` — configuration reference
- `README.md` — this file
- `scripts/deploy.sh` — the deploy script itself (sourced from the top-level `scripts/` directory in the repo)

> **After updating:** `config.ini` is never touched. Check `config.example.ini` for any new keys added since your last update and copy the ones you want into `config.ini`.

---

## Configuration

All settings live in `config.ini` (copied from `config.example.ini`). Every key has a built-in default — only change what you need.

| Section | Key | Default | Description |
|---|---|---|---|
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
| `[forecast]` | `enabled` | `false` | Enable WeatherFlow Better Forecast polling |
| `[forecast]` | `station_id` | _(empty)_ | WeatherFlow station ID — **required** |
| `[forecast]` | `api_key` | _(empty)_ | WeatherFlow personal API key — **required** |
| `[forecast]` | `location` | `home` | Slug used in MQTT topic: `forecast-<location>` |
| `[forecast]` | `interval_min` | `30` | Polling interval in minutes |
| `[forecast]` | `forecast_hours` | `48` | Max hourly entries published (API provides up to 120) |

---

## Home Assistant Integration

### Sensor auto-discovery

With `discovery = true` in `[homeassistant]` and `retain = true` in `[mqtt]`, the service publishes retained MQTT discovery messages and Home Assistant automatically creates:

- **Tempest ST-xxxxx** — all raw observation fields and derived metrics
- **Tempest HB-xxxxx** — hub status sensors
- **Forecast \<location\>** — 9 sensors auto-discovered when `[forecast] enabled = true`:
  - 7 current-condition sensors (condition, temperature, humidity, wind speed, wind bearing, pressure, dew point)
  - 2 forecast-array sensors (Hourly Forecast, Daily Forecast) — state = entry count, attributes contain the full forecast data

### Weather card with hourly/daily forecast

HA MQTT discovery does not support `weather` entities, and the `mqtt: weather:` configuration key is also invalid. Use HA's `template: weather:` platform instead, which reads from the sensors above.

Add the following to `configuration.yaml` and restart Home Assistant:

```yaml
template:
  - weather:
      - name: "Forecast Home"
        unique_id: "tempest_forecast_home_weather"
        condition_template: "{{ states('sensor.forecast_home_condition') }}"
        temperature_template: "{{ states('sensor.forecast_home_temperature') | float(0) }}"
        temperature_unit: "°C"
        humidity_template: "{{ states('sensor.forecast_home_humidity') | float(0) }}"
        pressure_template: "{{ states('sensor.forecast_home_sea_level_pressure') | float(0) }}"
        pressure_unit: "hPa"
        wind_speed_template: "{{ states('sensor.forecast_home_wind_speed') | float(0) }}"
        wind_speed_unit: "m/s"
        wind_bearing_template: "{{ states('sensor.forecast_home_wind_bearing') | float(0) }}"
        forecast_hourly_template: "{{ state_attr('sensor.forecast_home_hourly_forecast', 'forecasts') }}"
        forecast_daily_template: "{{ state_attr('sensor.forecast_home_daily_forecast', 'forecasts') }}"
```

Replace `home` in the entity IDs with your `location` slug (hyphens become underscores). If the IDs don't match what HA created, verify the exact names in **Developer Tools → States**. The correct YAML for your location is also logged at INFO level the first time the forecast publishes.

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
| Forecast not appearing | Verify `station_id` and `api_key` are both set in `[forecast]`. Check logs for HTTP errors from the WeatherFlow API. |
| Forecast weather card missing in HA | HA does not support `mqtt: weather:` — use the `template: weather:` block from the [Home Assistant section](#weather-card-with-hourlydaily-forecast). After restarting HA, verify entity IDs in **Developer Tools → States** if the template doesn't populate. |
| No data after hub reboot | The hub re-announces within ~60 s — wait and check logs. |
