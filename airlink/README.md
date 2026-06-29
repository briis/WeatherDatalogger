# Davis AirLink Datalogger

Polls the Davis AirLink local REST API and publishes air quality observations to MQTT.

## MQTT Topic

```
weatherdatalogger/airlink-<device_id>/observation
```

`<device_id>` is the AirLink's MAC address (e.g. `001D0A100A5A`), taken from the `did` field of the API response.

## Fields Published

All fields in a single flat JSON object.

| Field | Unit | Description |
|---|---|---|
| `pm_1_ugm3` | µg/m³ | PM1.0 (2-min average) |
| `pm_2p5_ugm3` | µg/m³ | PM2.5 (2-min average) |
| `pm_2p5_1h_ugm3` | µg/m³ | PM2.5 1-hour average |
| `pm_2p5_3h_ugm3` | µg/m³ | PM2.5 3-hour average |
| `pm_2p5_24h_ugm3` | µg/m³ | PM2.5 24-hour average |
| `pm_2p5_nowcast_ugm3` | µg/m³ | PM2.5 NowCast (EPA 12-h weighted avg) |
| `pm_10_ugm3` | µg/m³ | PM10 (2-min average) |
| `pm_10_1h_ugm3` | µg/m³ | PM10 1-hour average |
| `pm_10_3h_ugm3` | µg/m³ | PM10 3-hour average |
| `pm_10_24h_ugm3` | µg/m³ | PM10 24-hour average |
| `pm_10_nowcast_ugm3` | µg/m³ | PM10 NowCast |
| `aqi_pm2p5` | — | US EPA AQI computed from PM2.5 NowCast |
| `aqi_pm10` | — | US EPA AQI computed from PM10 NowCast |
| `air_temperature_c` | °C | Internal temperature (converted from °F) |
| `relative_humidity_pct` | % | Relative humidity |
| `dew_point_c` | °C | Dew point (converted from °F) |
| `pct_pm_data_1h` | % | PM data completeness — last 1 hour |
| `pct_pm_data_3h` | % | PM data completeness — last 3 hours |
| `pct_pm_data_24h` | % | PM data completeness — last 24 hours |
| `pct_pm_data_nowcast` | % | PM data completeness — NowCast window |
| `serial_number` | — | Device MAC (`did` from API) |
| `timestamp` | Unix s | Observation timestamp |

> **Note:** Temperature and humidity are measured by sensors inside the AirLink enclosure, used for PM reading correction. They are not a substitute for an outdoor weather station.

## Installation

### 1. Install service files

The deploy script copies everything automatically:

```bash
sudo bash /opt/tempest-datalogger/scripts/deploy.sh
```

Files are installed to `/opt/airlink-datalogger/`.

### 2. Configure

```bash
cp /opt/airlink-datalogger/config.example.ini /opt/airlink-datalogger/config.ini
nano /opt/airlink-datalogger/config.ini
```

Set `[airlink] host` to the AirLink's IP address. Point `[mqtt]` at your broker.

### 3. Enable and start

```bash
systemctl enable --now airlink-datalogger
journalctl -u airlink-datalogger -f
```

## Configuration Reference

```ini
[airlink]
host       = 192.168.1.43   # AirLink IP address
port       = 80              # HTTP port (default 80)
interval_s = 60              # Poll interval in seconds
timeout_s  = 10              # HTTP request timeout

[mqtt]
broker     = localhost
port       = 1883
username   =
password   =
tls        = false
base_topic = weatherdatalogger
client_id  = airlink-datalogger
retain     = false
qos        = 0

[logging]
level = INFO
file  =                      # empty = stdout / journald only

[homeassistant]
discovery        = false
discovery_prefix = homeassistant
```

## Home Assistant Discovery

Set `[homeassistant] discovery = true` to auto-create an **AirLink \<device_id\>** device in Home Assistant with 18 sensors covering all PM readings, AQI, temperature, humidity, and data quality metrics.

## AQI Calculation

AQI is computed from the NowCast concentration using the US EPA linear interpolation formula. NowCast is a 12-hour weighted average designed for real-time air quality displays — it responds faster than a straight 24-hour average while still smoothing short-term spikes.
