# WeatherDatalogger

> **⚠️ Active development:** This repository is under active development. Breaking changes — to schemas, MQTT topics/payloads, configuration, or service behavior — may occur without notice until a stable release is tagged.

A unified weather data pipeline that collects data from multiple weather station brands and publishes everything to a single MQTT broker under a common topic namespace (`weatherdatalogger/`). Downstream consumers — Home Assistant, databases, dashboards — subscribe to MQTT and are completely decoupled from the hardware.

---

## Services

### Station loggers (hardware → MQTT)

| Directory | Hardware | Status |
|---|---|---|
| [`weatherdatalogger/tempest/`](weatherdatalogger/tempest/) | WeatherFlow Tempest (UDP → MQTT) | Active |
| [`davis/`](davis/) | Davis Vantage Vue (ESP32-WROOM-32 + CC1101, ESPHome) | Active — field-tested |
| [`weatherdatalogger/airlink/`](weatherdatalogger/airlink/) | Davis AirLink air quality sensor (HTTP polling → MQTT) | Active |
| [`weatherdatalogger/meteobridge/`](weatherdatalogger/meteobridge/) | Meteobridge (HTTP polling → MQTT full observation) | Active, optional |
| [`weatherdatalogger/visualcrossing/`](weatherdatalogger/visualcrossing/) | Visual Crossing Weather API forecast (HTTP polling → MQTT) | Active, optional — lat/lon-based, no station hardware required |

### Infrastructure (MQTT → storage)

| Directory | Purpose | Status |
|---|---|---|
| [`weatherdatalogger/database/`](weatherdatalogger/database/) | WeatherDB Writer — persists observations to MariaDB | Active |

---

## MQTT Topic Namespace

```
weatherdatalogger/
  tempest-<serial>/         ← WeatherFlow Tempest
    observation
    rapid_wind
    rain_start
    lightning
    device_status
    hub_status
  forecast-<provider>-<location>/  ← forecast provider(s), e.g. forecast-visualcrossing-home (optional)
    current
    forecast_hourly
    forecast_daily
  davis-<id>/               ← Davis Vantage Vue (ESPHome, active)
    observation
    rapid_wind
    device_status
  davis-vantage-receiver/   ← Static control topics — OPTIONAL manual rain correction
    set_daily_rain            (Davis's own rain fields are computed standalone
    set_rain_rate              from its RF tip counter; nothing depends on these)
  airlink-<did>/            ← Davis AirLink air quality sensor
    observation
  meteobridge-<mac>/        ← Meteobridge (optional)
    observation
```

Meteobridge (`weatherdatalogger/meteobridge/`) is a full station like any other — `station_roles` (see `weatherdatalogger/database/`) decides which physical station actually supplies each field of `combined_realtime` when more than one reports the same kind of reading.

---

## Installation (Debian / Proxmox LXC)

### 1. Install prerequisites

```bash
apt update && apt install -y python3 python3-venv git mariadb-server
```

On Debian, MariaDB is already secured by default — root access requires no password and is restricted to the system `root` user via Unix socket authentication.

### 2. Create a dedicated service user

```bash
useradd -r -s /usr/sbin/nologin weatherdatalogger
```

### 3. Bootstrap the deploy script

The deploy script is the only file needed to bootstrap:

```bash
mkdir -p /opt/weatherdatalogger/scripts
curl -fsSL https://raw.githubusercontent.com/briis/WeatherDatalogger/main/weatherdatalogger/scripts/deploy.sh -o /opt/weatherdatalogger/scripts/deploy.sh
chmod +x /opt/weatherdatalogger/scripts/deploy.sh
```

### 4. Run the deploy script (first time)

```bash
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

This clones the repo, installs all service files under `/opt/weatherdatalogger/`, creates Python virtual environments, installs dependencies, and registers the systemd unit files. It also prints first-time setup instructions since no `config.ini` exists yet.

### 5. Configure MariaDB for network access

By default MariaDB on Debian binds to `127.0.0.1` only. Change it to listen on all interfaces so other hosts on the network can connect:

```bash
sed -i 's/^bind-address\s*=.*/bind-address = 0.0.0.0/' /etc/mysql/mariadb.conf.d/50-server.cnf
systemctl restart mariadb
```

Verify:

```bash
ss -tlnp | grep 3306
# Expected: 0.0.0.0:3306
```

### 6. Create the database

Edit the password in the SQL script before running:

```bash
nano /opt/weatherdatalogger/database/01_create_database.sql
mariadb -u root < /opt/weatherdatalogger/database/01_create_database.sql
```

### 7. Create the tables

```bash
mariadb -u root weatherdatalogger \
    < /opt/weatherdatalogger/database/02_create_tables.sql
```

This creates all schema objects in one step: the `stations`, `realtime`, `history`, and `history_charting` tables; the `combined_realtime` view; and the `evt_aggregate_history_charting` event.

### 8. Enable the MariaDB event scheduler

The `history_charting` table is populated by a MariaDB event that runs every 10 minutes. The event scheduler is off by default and must be enabled once:

```bash
# Persistent — survives reboots (recommended)
echo -e "[mysqld]\nevent_scheduler = ON" \
    | sudo tee /etc/mysql/mariadb.conf.d/99-local.cnf
sudo systemctl restart mariadb
```

Verify:

```bash
mysql --defaults-extra-file=/opt/weatherdatalogger/db.cnf \
    -e "SHOW VARIABLES LIKE 'event_scheduler';"
# Expected: event_scheduler | ON
```

### 9. Create the shared config file

All five services read from a single configuration file at `/opt/weatherdatalogger/config.ini`. The deploy script never overwrites this file once it exists.

```bash
cp /opt/weatherdatalogger/config.example.ini /opt/weatherdatalogger/config.ini
nano /opt/weatherdatalogger/config.ini
```

**Every station/forecast service is off by default** (`enabled = false`) — set `enabled = true` under each one you actually own, then fill in that service's other required fields:

| Field | Section | Description |
|---|---|---|
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |
| `password` | `[database]` | Database password (set in step 6) |
| `enabled` | `[tempest]` | Set `true` if you have a WeatherFlow Tempest |
| `enabled`, `host` | `[airlink]` | Set `true` + IP/hostname if you have a Davis AirLink |
| `enabled`, `host` | `[meteobridge]` | Set `true` + IP/hostname if you have a Meteobridge Pro |
| `enabled`, `api_key`, `latitude`, `longitude` | `[visualcrossing]` | Set `true` + your API key/coordinates for Visual Crossing forecast data |

A service left `enabled = false` idles rather than crash-loops, so it's safe to leave every optional one at its default and enable only what you own.

### 10. Enable and start the services

```bash
# DB writer (must be running before station loggers send data)
systemctl enable --now weatherdb-writer
journalctl -u weatherdb-writer -f

# Tempest datalogger (skip if [tempest] enabled = false)
systemctl enable --now tempest-datalogger
journalctl -u tempest-datalogger -f

# AirLink datalogger (skip if [airlink] enabled = false)
systemctl enable --now airlink-datalogger
journalctl -u airlink-datalogger -f

# Meteobridge datalogger (skip if [meteobridge] enabled = false)
systemctl enable --now meteobridge-datalogger
journalctl -u meteobridge-datalogger -f

# Visual Crossing forecast (skip if [visualcrossing] enabled = false)
systemctl enable --now visualcrossing-datalogger
journalctl -u visualcrossing-datalogger -f
```

On the first observation you should see a `Registered station` line in the DB writer log, then `Wrote … @ …` every 10–15 s.

> `systemctl enable`/`disable` and `config.ini`'s `enabled` flag are
> independent — a service can be systemd-enabled (starts on boot) yet
> config-disabled (starts, logs, and immediately idles), and vice versa.
> Both need to say "yes" for a service to actually do anything.

---

## Updating

```bash
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

The deploy script:
- Clones the latest code from GitHub to a temporary staging directory
- Updates all production files for every service
- Records the installed version to `/opt/weatherdatalogger/VERSION`
- Applies any pending SQL migrations to the database
- Updates Python dependencies in each virtual environment
- Syncs systemd unit files and reloads the daemon if changed
- Restarts each service — only if it's systemd-enabled *and* (for station/forecast services) `enabled = true` in its own `config.ini` section; a config-disabled service is skipped rather than restarted, since it would just idle back down

Check what's currently installed anytime with:

```bash
cat /opt/weatherdatalogger/VERSION
```

Include this when reporting a bug or requesting a change — it pins down exactly which commit is running. See [`CHANGELOG.md`](CHANGELOG.md) for what changed in each version.

> **Breaking change (this version):** Tempest, AirLink, and Meteobridge now
> require an explicit `enabled = true` in their own `config.ini` section,
> matching how Visual Crossing already worked — previously Tempest always
> ran and AirLink/Meteobridge ran whenever `host` was set. Existing
> deployments will see a `WARNING` in that service's journal after
> upgrading (`[<service>] enabled is not set in config.ini — defaulting to
> disabled...`) and the service will idle until you add `enabled = true`
> under its section in `config.ini` and restart it.

`/opt/weatherdatalogger/config.ini` is never touched — your local configuration is always preserved.

---

## Development

Shared tooling lives at the repo root and applies to all services:

```bash
bash scripts/lint        # ruff format + ruff check --fix (all Python in repo)
```

Requirements: `pip install -r requirements-dev.txt`
