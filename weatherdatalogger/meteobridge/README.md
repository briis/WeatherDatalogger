# Meteobridge Datalogger

Polls a Meteobridge's local REST template API and publishes a full weather observation to MQTT — a full station integration, not just a correction feed.

The Meteobridge is wired directly to the same Vantage Vue ISS as the `davis-vantage-receiver` ESPHome device, plus its own onboard barometer/indoor sensor and a second attached station providing solar/UV/lightning. Since every station publishes the same field names, [`station_roles`](../database/02_create_tables.sql) decides which physical station actually supplies each field of `combined_realtime` — point any role at `meteobridge` there to prefer this station's reading over Davis/Tempest/AirLink.

**This replaces the old rain-correction service.** Earlier versions of this script only pushed `set_daily_rain`/`set_rain_rate` corrections into the Davis receiver's own MQTT control topics and had no database rows of its own — see `AGENT.md` ("Rain accumulation & rate") for that history. That correction was never depended on: the Davis receiver's own rain fields are computed standalone from its RF tip counter, so retiring the push doesn't affect that device. If you'd rather source `combined_realtime`'s `rain` role from this station instead of Davis, that's a `station_roles` update (see below), not a firmware change.

## MQTT Topic

```
weatherdatalogger/meteobridge-<mac>/observation
```

`<mac>` is the Meteobridge's own MAC address (`[mbsystem-mac]`), colons replaced with hyphens (e.g. `94-A4-08-E8-B0-41`).

## Fields Published

All fields in a single flat JSON object, matching the `realtime`/`history` table columns (see `database/02_create_tables.sql`).

| Field | Unit | Source |
|---|---|---|
| `wind_lull_ms` / `wind_avg_ms` / `wind_gust_ms` | m/s | Meteobridge `wind0wind` -min1/-avg1/-max1 |
| `wind_direction_deg` | ° | Meteobridge `wind0dir-act` |
| `wind_beaufort` / `wind_beaufort_description` | — | Computed client-side from `wind_avg_ms`, same WMO thresholds and English/Danish wording as `davis-vantage-receiver.yaml` |
| `station_pressure_mb` / `sea_level_pressure_mb` | hPa | Meteobridge `thb0press-act` / `thb0seapress-act` (onboard barometer) |
| `pressure_trend_mb` / `sea_level_pressure_trend_mb` | hPa | Meteobridge `thb0press-delta3h` / `thb0seapress-delta3h` |
| `pressure_trend` / `sea_level_pressure_trend` | — | Rising/Steady/Falling, derived client-side from the deltas above (±1.0 hPa threshold) |
| `air_temperature_c` / `relative_humidity_pct` / `dew_point_c` | °C / % / °C | Meteobridge `th0temp` / `th0hum` / `th0dew` (outdoor ISS) |
| `wet_bulb_c` / `heat_index_c` / `wind_chill_c` | °C | Meteobridge `th0wetbulb` / `th0heatindex` / `wind0chill` |
| `delta_t_c` | °C | Computed client-side: `air_temperature_c - wet_bulb_c` |
| `feels_like_c` | °C | Computed client-side from the fetched heat index/wind chill, same selection thresholds as `tempest_datalogger.py` |
| `vapor_pressure_mb` / `air_density_kgm3` | hPa / kg/m³ | Computed client-side, same formulas as `tempest_datalogger.py` |
| `uv_index` | — | Meteobridge `uv0index-act` |
| `solar_radiation_wm2` | W/m² | Meteobridge `sol0rad-act` |
| `rain_rate_mmh` | mm/h | Meteobridge `rain0rate-act` |
| `rain_accumulation_mm` | mm | Meteobridge `rain0total-daysum` (today's accumulated total) |
| `indoor_temperature_c` / `indoor_humidity_pct` | °C / % | Meteobridge `thb0temp-act` / `thb0hum-act` — wherever the Meteobridge unit itself sits, not necessarily a comfortable room (see note below) |
| `lightning_last_detected` / `lightning_count_3h` / `lightning_min_dist_3h_km` / `lightning_max_dist_3h_km` | — / — / km / km | Derived client-side from Meteobridge's `lgt0total-daysum` counter and `lgt0dist-act` — see "Lightning" below |
| `serial_number` | — | Meteobridge MAC, colons replaced with hyphens |
| `timestamp` | Unix s | Meteobridge `epoch` |

`illuminance_lux`, `battery_volts`, and `battery_low` have no known Meteobridge macro and are omitted (NULL in the database).

> **Note:** In testing, this unit's `thb0` indoor sensor read ~47°C — it's evidently mounted somewhere hot (attic, near equipment), not in a living space. Worth checking before wiring `indoor_temperature_c` into a "Room Temperature" Home Assistant card.

## Lightning

Meteobridge only exposes a cumulative daily strike counter (`lgt0total-daysum`) and the *current* strike distance (`lgt0dist-act`) — there's no per-strike timestamp macro (`-time` was tried against real hardware and isn't supported). New strikes are detected by watching the counter increase between polls; each detected strike is recorded (at the current poll's distance reading — the counter alone can't attribute distance per-strike if several land between polls) into a rolling 3-hour window, persisted across restarts in `meteobridge_lightning.json` (see `[meteobridge] data_dir`) — the same approach `tempest_datalogger.py` uses for WeatherFlow's own discrete strike events, just fed from a polled counter instead. A counter *decrease* is treated as Meteobridge's own local-midnight reset, not negative strikes.

## Installation

### 1. Install service files

The deploy script copies everything automatically:

```bash
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

Files are installed to `/opt/weatherdatalogger/meteobridge/`.

### 2. Configure

All services share a single config file. If it doesn't exist yet:

```bash
cp /opt/weatherdatalogger/config.example.ini /opt/weatherdatalogger/config.ini
nano /opt/weatherdatalogger/config.ini
```

**Required before first start** — the service will log an error and idle (not crash-loop) until this is set:

| Key | Section | What to set |
|---|---|---|
| `host` | `[meteobridge]` | IP address or hostname of the Meteobridge (e.g. `192.168.1.252`) |
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |

Everything else has sensible defaults and can be left as-is. This service is entirely optional — leave `host` empty if you don't have a Meteobridge.

### 3. Enable and start

```bash
systemctl enable --now meteobridge-datalogger
journalctl -u meteobridge-datalogger -f
```

You should see an `observation → weatherdatalogger/meteobridge-<mac>/observation` line every poll interval.

### 4. Point a role at it (optional)

By default, a new `meteobridge` station is logged to `realtime`/`history` but doesn't feed `combined_realtime` — the `station_roles` table still points wind/rain/temp_humidity/pressure/solar_uv/lightning wherever they already were. To prefer this station for a given role:

```sql
UPDATE station_roles SET station_type = 'meteobridge' WHERE role = 'wind';
```

## Configuration Reference

Settings live in the shared `/opt/weatherdatalogger/config.ini`. Meteobridge-specific keys:

```ini
[meteobridge]
host       =               # REQUIRED — Meteobridge IP address or hostname
port       = 80            # HTTP port (default 80)
username   = meteobridge   # HTTP basic auth username — Meteobridge's own factory default; empty = no auth header sent
password   =
interval_s = 60            # Poll interval in seconds
timeout_s  = 10             # HTTP request timeout
language   = en            # wind_beaufort_description language — "en" or "da"
data_dir   =                # Persisted lightning-window state file directory; empty = same as config file
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

Set `[homeassistant] discovery = true` to auto-create a **Meteobridge \<mac\>** device in Home Assistant with sensors covering wind, pressure (+ trend), temperature/humidity, solar/UV, rain, indoor conditions, and the lightning summary.

## How the request works

Meteobridge's `template.cgi` endpoint substitutes square-bracket macros in a query string before returning the result, as a single quote-free comma-separated line (see `MB_TEMPLATE` in `meteobridge_datalogger.py`) — a JSON-shaped template was tried first but real hardware backslash-escapes every quote in the output (some Meteobridge firmware applies PHP/CGI-style `addslashes()`), breaking `json.loads`. Each macro carries a `:fallback` suffix so one missing/unavailable sensor degrades that single field instead of losing the whole poll. See the [Meteobridge Templates wiki](https://www.meteobridge.com/wiki/index.php?title=Templates) for the macro suffix reference, and the comment block above `_TEMPLATE_FIELDS` in the script for which macro suffixes were validated against real hardware versus inferred by symmetry.
