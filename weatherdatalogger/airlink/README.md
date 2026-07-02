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
| `caqi_pm2p5` | — | EU CAQI (CITEAIR) computed from current PM2.5 concentration |
| `caqi_pm10` | — | EU CAQI (CITEAIR) computed from current PM10 concentration |
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
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

Files are installed to `/opt/weatherdatalogger/airlink/`.

### 2. Configure

All services share a single config file. If it doesn't exist yet:

```bash
cp /opt/weatherdatalogger/config.example.ini /opt/weatherdatalogger/config.ini
nano /opt/weatherdatalogger/config.ini
```

**Required before first start** — the service will not poll until these are set:

| Key | Section | What to set |
|---|---|---|
| `host` | `[airlink]` | IP address or hostname of the AirLink (e.g. `192.168.1.43`) |
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |

Everything else has sensible defaults and can be left as-is.

### 3. Enable and start

```bash
systemctl enable --now airlink-datalogger
journalctl -u airlink-datalogger -f
```

## Configuration Reference

Settings live in the shared `/opt/weatherdatalogger/config.ini`. AirLink-specific keys:

```ini
[airlink]
host       =               # REQUIRED — AirLink IP address or hostname
port       = 80            # HTTP port (default 80)
interval_s = 60            # Poll interval in seconds
timeout_s  = 10            # HTTP request timeout
```

Shared keys used by this service:

```ini
[mqtt]
broker     = localhost     # REQUIRED — MQTT broker hostname or IP
port       = 1883
username   =
password   =
tls        = false
base_topic = weatherdatalogger
retain     = false
qos        = 0

[logging]
level = INFO
file  =

[homeassistant]
discovery        = false
discovery_prefix = homeassistant
```

## Home Assistant Discovery

Set `[homeassistant] discovery = true` to auto-create an **AirLink \<device_id\>** device in Home Assistant with 20 sensors covering all PM readings, AQI (both standards), temperature, humidity, and data quality metrics.

## AQI Calculation

Two independent air quality index standards are computed, since consoles/dashboards outside the US commonly expect a different scale than the US EPA one:

- **`aqi_pm2p5`/`aqi_pm10`** — US EPA AQI (0-500 scale), computed from the **NowCast** concentration using the standard linear interpolation formula. NowCast is a 12-hour weighted average designed for real-time air quality displays — it responds faster than a straight 24-hour average while still smoothing short-term spikes.
- **`caqi_pm2p5`/`caqi_pm10`** — EU CAQI ([CITEAIR](https://www.airqualitynow.eu) Common Air Quality Index, nominally 0-100 but open-ended above that for genuinely poor air), computed from the **current** (not NowCast) concentration, since CAQI is designed as a real-time hourly index rather than a smoothed one. The official CAQI bands only go up to 100 ("Very High"); values beyond that are extrapolated at the same index-per-µg/m³ slope as the High→Very High transition, capped at 200, so a smog-level reading still returns a number rather than `null`.
