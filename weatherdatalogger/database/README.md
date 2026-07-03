# WeatherDB Writer

Subscribes to MQTT observation topics published by the weather station loggers and persists every reading to MariaDB. Runs as a standalone systemd service so database writes are completely decoupled from the station loggers.

> **Installation:** Follow the [server installation guide](../README.md#installation) first, then return here to configure the DB writer.

---

## What it does

- Subscribes to `{base_topic}/+/observation` — the `+` wildcard covers all stations
- Auto-registers new stations in the `stations` table on first observation
- **Upserts** the `realtime` table — always holds the single latest reading per station
- **Appends** the `history` table — full time-series log for charting and trend analysis
- Reconnects automatically to both MQTT and MariaDB on connection loss (handles both `OperationalError` and `InterfaceError`)

All timestamps are stored in **UTC** as naive `DATETIME` values. Use `UTC_TIMESTAMP()` (not `NOW()`) when querying if the MariaDB server runs in a non-UTC timezone.

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
| `aqi_pm2p5`, `aqi_pm10` | US EPA AQI, from PM NowCast (AirLink) |
| `caqi_pm2p5`, `caqi_pm10` | EU CAQI (CITEAIR), from current PM concentration (AirLink) |

### `combined_realtime` (view)

A single-row view that merges the latest readings from all station types into one record. Most weather fields are sourced from the `davis` station; pressure, lightning, UV, solar, illuminance, wet bulb/delta T, air density, and battery voltage come from `tempest` (the Davis ISS has no sensors for these); air quality fields come from `airlink`. Tempest-only and air quality columns are `NULL` until those stations are registered.

**Use this view as the primary source for dashboards and downstream consumers** — it hides the per-station layout of `realtime` and provides a unified snapshot of all current conditions.

| Column | Source |
|---|---|
| `recorded_at` | Davis — timestamp of the latest weather observation |
| `tempest_recorded_at` | Tempest — timestamp of the latest Tempest-sourced observation |
| `airlink_recorded_at` | AirLink — timestamp of the latest air quality observation |
| Wind, temperature, humidity, dew point, feels like/heat index/wind chill, rain, vapor pressure | Davis |
| `davis_battery_low` | Davis — low-battery flag (Davis reports low/ok, not voltage) |
| Pressure, lightning, UV, solar, illuminance, wet bulb, delta T, air density, `battery_volts` | Tempest |
| `pm_*`, `aqi_*`, `caqi_*` | AirLink |

### `combined_realtime_stats` (view)

A single-row view of derived/calculated stats, computed on demand from raw `history` (not `history_charting`, which lags up to ~20 min and is too coarse for a rolling 10-minute window). `wind` and `rain` are sourced via `station_roles`, same as `combined_realtime`.

| Column | Meaning |
|---|---|
| `wind_gust_high_today` | Highest wind gust since local (Europe/Copenhagen) midnight |
| `wind_bearing_avg_day` | Circular-mean wind bearing since local midnight |
| `wind_bearing_avg_10min` | Circular-mean wind bearing over the trailing 10 minutes (rolling, not clock-aligned) |
| `rain_total_yesterday` | Total rainfall for the full previous local calendar day — `MAX(rain_accumulation_mm)`, not `SUM`, since that column is a running cumulative "so far today" counter (resets at local midnight), not a per-observation delta |

"Today"/"yesterday" boundaries use `CONVERT_TZ(..., 'UTC', 'Europe/Copenhagen')` since `recorded_at` is stored as naive UTC. This requires the MariaDB named-timezone tables to be loaded (`mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root mysql`) — if they're missing, `CONVERT_TZ` silently returns `NULL` and the day-boundary columns will all be `NULL` (the 10-min rolling column is unaffected, since it doesn't need a day boundary).

### `history_charting`

Pre-aggregated 10-minute summaries combining Davis, Tempest, and AirLink data into a single row per window, using the same per-field source split as `combined_realtime`. Intended for charting where raw per-observation granularity is unnecessary. Populated automatically by the `evt_aggregate_history_charting` MariaDB event.

`window_start` is a clock-aligned UTC timestamp (00:00, 00:10, 00:20, …) and is the unique key. The event looks back 30 minutes on each run so late-arriving messages are captured, and `INSERT IGNORE` makes re-runs safe.

| Column group | Aggregation | Notes |
|---|---|---|
| `wind_avg_ms` | AVG | 10-min mean wind speed (Davis) |
| `wind_lull_ms` | MIN | Calmest reading in window (Davis) |
| `wind_gust_ms` | MAX | Peak gust in window (Davis) |
| `wind_direction_deg` | Circular AVG | Uses `ATAN2(AVG(SIN), AVG(COS))` — handles 0°/360° boundary correctly (Davis) |
| Temperature, humidity, dew point, feels like/heat index/wind chill, vapor pressure | AVG | Davis |
| Pressure, illuminance, UV, solar, wet bulb, delta T, air density, `battery_volts` | AVG | Tempest |
| `rain_accumulation_mm` | MAX | Davis reports a cumulative "rain so far today" counter (resets at local midnight), not a per-observation delta — MAX gives the running total as of the window's end, not a per-window delta |
| `rain_rate_mmh` | MAX | Peak rain rate in window (Davis) |
| `pressure_trend`, `sea_level_pressure_trend` | Last value | Most recent text label in window (Tempest) |
| Lightning fields | MAX / MIN | Rolling 3-hour counters from device (Tempest) |
| `davis_battery_low` | MAX | True if a low-battery reading occurred anywhere in the window |
| `pm_*` (instant) | AVG | AirLink |
| `aqi_pm2p5`, `aqi_pm10` | MAX | Worst-case US AQI in window (AirLink) |
| `caqi_pm2p5`, `caqi_pm10` | MAX | Worst-case EU CAQI in window (AirLink) |

**Requires the MariaDB event scheduler** — see [server installation step 8](../../README.md#8-enable-the-mariadb-event-scheduler).

---

## Schema Migrations

Future schema changes (new columns, indexes, etc.) are handled as numbered SQL files in the `migrations/` directory. The deploy script applies any file not yet recorded in the `schema_migrations` table automatically on each deploy.

To add a migration:

1. Create `database/migrations/YYYYMMDD_description.sql` with the change
2. Commit and push
3. Run `sudo bash /opt/weatherdatalogger/scripts/deploy.sh`

The migration is recorded by filename so it is applied exactly once.

---

## Resetting From Scratch

To wipe all data and rebuild the database from the current schema + migrations (e.g. clearing out test data before going into production) — **this is destructive and irreversible**, take a backup first:

```bash
# 1. Stop the writer so nothing writes mid-rebuild
sudo systemctl stop weatherdb-writer

# 2. Backup, even if you don't intend to keep the data
mysqldump --defaults-extra-file=/opt/weatherdatalogger/db.cnf weatherdatalogger \
    > ~/weatherdatalogger_backup_$(date +%Y%m%d).sql

# 3. Drop and recreate the database + base schema from scratch, as root
mysql -u root -p -e "DROP DATABASE weatherdatalogger;"
mysql -u root -p < weatherdatalogger/database/01_create_database.sql
mysql -u weatherlogger -p weatherdatalogger < weatherdatalogger/database/02_create_tables.sql

# 4. Re-run the deploy script — schema_migrations is now empty, so it will
#    apply every migration file in order and restart weatherdb-writer
#    since it's already enabled
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

Important: `deploy.sh` clones from GitHub `main`, not the local working tree — **commit and push any pending schema/migration changes before running step 4**, or the rebuild will silently skip them.

Notes:
- Step 3's `01_create_database.sql` uses `CREATE USER IF NOT EXISTS`, so it won't touch the existing `weatherlogger` password if that user already exists — `db.cnf` stays valid, no need to regenerate it.
- `stations` repopulates automatically as MQTT observations arrive; `station_roles` reseeds to its defaults (`wind`/`temp_humidity`/`rain` → `davis`, `pressure`/`solar_uv`/`lightning` → `tempest`, `air_quality` → `airlink`) — worth checking those still match your actual hardware afterward if you'd previously reassigned any role.
- If named-timezone support (`CONVERT_TZ` with zone names, used by `combined_realtime_stats`) was set up on this host before, it survives the DB rebuild — it's stored in the separate `mysql` system database, not `weatherdatalogger`.
