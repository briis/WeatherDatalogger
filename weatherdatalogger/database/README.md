# WeatherDB Writer

Subscribes to MQTT observation topics published by the weather station loggers and persists every reading to MariaDB. Runs as a standalone systemd service so database writes are completely decoupled from the station loggers.

> **Installation:** Follow the [server installation guide](../README.md#installation) first, then return here to configure the DB writer.

---

## What it does

- Subscribes to `{base_topic}/+/observation` — the `+` wildcard covers all stations
- Auto-registers new stations in the `stations` table on first observation
- **Upserts** the `realtime` table — always holds the single latest reading per station
- **Appends** the `history` table — full time-series log for charting and trend analysis
- Reconnects automatically to both MQTT and MariaDB on connection loss

---

## Setup

After completing the [server installation](../README.md#installation), edit the shared config file:

```bash
nano /opt/weatherdatalogger/config.ini
```

Minimum required settings for the DB writer:

```ini
[mqtt]
broker = 192.168.1.10   # IP or hostname of your MQTT broker

[database]
password = your_db_password_here
```

Enable and start the service:

```bash
systemctl enable --now weatherdb-writer
```

Verify:

```bash
journalctl -u weatherdb-writer -f
```

On the first observation you should see a `Registered station` line, then `Wrote … @ …` every 10-15 s.

---

## Configuration

All settings live in the shared `/opt/weatherdatalogger/config.ini`. The DB writer reads these sections:

| Section | Key | Default | Description |
|---|---|---|---|
| `[mqtt]` | `broker` | `localhost` | MQTT broker hostname or IP |
| `[mqtt]` | `port` | `1883` | MQTT broker port |
| `[mqtt]` | `username` | _(empty)_ | MQTT username |
| `[mqtt]` | `password` | _(empty)_ | MQTT password |
| `[mqtt]` | `tls` | `false` | Enable TLS/SSL |
| `[mqtt]` | `base_topic` | `weatherdatalogger` | Must match the datalogger's `base_topic` |
| `[database]` | `host` | `localhost` | MariaDB hostname or IP |
| `[database]` | `port` | `3306` | MariaDB port |
| `[database]` | `name` | `weatherdatalogger` | Database name |
| `[database]` | `user` | `weatherlogger` | Database user |
| `[database]` | `password` | _(empty)_ | Database password — **required** |
| `[logging]` | `level` | `INFO` | Log level: `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `[logging]` | `file` | _(empty)_ | Optional log file path (empty = stdout/journal only) |

---

## Database Schema

### `stations`

One row per physical device. Auto-populated on first observation.

| Column | Type | Description |
|---|---|---|
| `station_id` | `VARCHAR(32)` | Hardware serial number e.g. `ST-00000512`, `001D0A100A5A` |
| `station_type` | `VARCHAR(32)` | `tempest` \| `airlink` \| `davis` |
| `name` | `VARCHAR(128)` | Optional human-readable label |
| `created_at` | `DATETIME` | First seen timestamp |

### `realtime`

One row per station, replaced on every incoming observation. Primary key is `station_id`.

### `history`

Full append-only time-series. Every observation is inserted here. Indexed on `(station_id, recorded_at)` for efficient range queries.

Both `realtime` and `history` share the same observation columns:

| Column | Description |
|---|---|
| `recorded_at` | UTC timestamp of the observation |
| `wind_lull_ms`, `wind_avg_ms`, `wind_gust_ms` | Wind speed (m/s) |
| `wind_direction_deg` | Wind direction (°) |
| `station_pressure_mb`, `sea_level_pressure_mb` | Pressure (mbar) |
| `pressure_trend`, `sea_level_pressure_trend` | `Rising` \| `Steady` \| `Falling` |
| `air_temperature_c`, `relative_humidity_pct` | Temperature and humidity |
| `dew_point_c`, `wet_bulb_c`, `feels_like_c` | Derived temperature metrics |
| `uv_index`, `solar_radiation_wm2`, `illuminance_lux` | Solar sensors |
| `rain_accumulation_mm`, `rain_rate_mmh` | Precipitation |
| `lightning_last_detected`, `lightning_count_3h` | Lightning history |
| `battery_volts` | Device battery voltage |
| `pm_1_ugm3`, `pm_2p5_ugm3`, `pm_10_ugm3` | Particulate matter — current (AirLink) |
| `pm_2p5_nowcast_ugm3`, `pm_10_nowcast_ugm3` | PM NowCast values (AirLink) |
| `aqi_pm2p5`, `aqi_pm10` | US EPA AQI (AirLink) |

### `combined_realtime` (view)

A single-row view that merges the latest readings from all station types into one record. Weather fields are sourced from the `tempest` station; air quality fields from the `airlink` station. Air quality columns are `NULL` if no AirLink station has been registered yet.

**Use this view as the primary source for dashboards and downstream consumers** — it hides the per-station layout of `realtime` and provides a unified snapshot of all current conditions.

| Column | Source |
|---|---|
| `recorded_at` | Tempest — timestamp of the latest weather observation |
| `airlink_recorded_at` | AirLink — timestamp of the latest air quality observation |
| All weather columns | Tempest |
| `pm_*`, `aqi_*` | AirLink |

---

## Schema Migrations

Future schema changes (new columns, indexes, etc.) are handled as numbered SQL files in the `migrations/` directory. The deploy script applies any file not yet recorded in the `schema_migrations` table automatically on each deploy.

To add a migration:

1. Create `database/migrations/YYYYMMDD_description.sql` with the change
2. Commit and push
3. Run `sudo bash /opt/weatherdatalogger/scripts/deploy.sh`

The migration is recorded by filename so it is applied exactly once.
