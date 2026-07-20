# ![logo](images/weatherdatalogger_icon72x72.png) WeatherDatalogger

> **⚠️ Active development:** This repository is under active development. Breaking changes — to schemas, MQTT topics/payloads, configuration, or service behavior — may occur without notice until a stable release is tagged.

A unified weather data pipeline that collects data from multiple weather station brands and publishes everything to a single MQTT broker under a common topic namespace (`weatherdatalogger/`). Downstream consumers — Home Assistant, databases, dashboards — subscribe to MQTT and are completely decoupled from the hardware.

---

## Overview

**What you need to run this:**
- A Debian-based Linux host with root access and `systemd` — developed/tested on Debian 12/13 in a Proxmox LXC; other Debian/Ubuntu-family systemd hosts should work
- An MQTT broker reachable from that host (e.g. Mosquitto) — it doesn't have to run on the same machine
- MariaDB for persisted storage — installed and configured automatically by [`install.sh`](#installation-debian--proxmox-lxc), no separate setup required
- Network reachability from the host to whichever station hardware/forecast API you use below — Tempest specifically needs to be on the **same L2 network segment** (its hub broadcasts over UDP, which doesn't cross routed boundaries); the others just need plain HTTP reachability

**Supported weather stations** — own one or more, enable only the ones you actually have:

| Station | Connection |
|---|---|
| WeatherFlow Tempest | UDP broadcast on the local network |
| Davis Vantage Vue | Custom ESPHome receiver ([`ESPHome/davis/`](ESPHome/davis/) — flashed hardware, not a systemd service) |
| Davis AirLink (air quality) | HTTP polling |
| Meteobridge | HTTP polling |
| Custom Air Quality Monitor (PM2.5/PM10) | Custom ESPHome device ([`ESPHome/airquality/`](ESPHome/airquality/) — flashed hardware, not a systemd service; field-compatible with AirLink) |

**Supported forecast providers:**

| Provider | Notes |
|---|---|
| Visual Crossing | Free tier available; lat/lon-based, no station hardware required |

More than one station and more than one forecast provider can run at the same time — readings land in one shared schema, with whatever fields a given piece of hardware doesn't report simply left `NULL` (see `station_roles` in [`database/README.md`](weatherdatalogger/database/)). The `forecast-<provider>-<location>/` MQTT topic namespace and the `provider` column on the forecast tables (see [`visualcrossing/README.md`](weatherdatalogger/visualcrossing/)) mean additional forecast sources can be added later without disrupting Visual Crossing or each other.

Ready to set it up? Jump to [Installation](#installation-debian--proxmox-lxc).

---

## Services

### Station loggers (hardware → MQTT)

| Directory | Hardware | Status |
|---|---|---|
| [`weatherdatalogger/tempest/`](weatherdatalogger/tempest/) | WeatherFlow Tempest (UDP → MQTT) | Active |
| [`ESPHome/davis/`](ESPHome/davis/) | Davis Vantage Vue (M5Stack Core + CC1101, ESPHome) | Active — field-tested |
| [`weatherdatalogger/airlink/`](weatherdatalogger/airlink/) | Davis AirLink air quality sensor (HTTP polling → MQTT) | Active |
| [`weatherdatalogger/meteobridge/`](weatherdatalogger/meteobridge/) | Meteobridge (HTTP polling → MQTT full observation) | Active, optional |
| [`weatherdatalogger/visualcrossing/`](weatherdatalogger/visualcrossing/) | Visual Crossing Weather API forecast (HTTP polling → MQTT) | Active, optional — lat/lon-based, no station hardware required |
| [`ESPHome/airquality/`](ESPHome/airquality/) | Custom air quality monitor (ESP32-C6 + SDS011 + BME280, ESPHome, field-compatible with AirLink) | Active |

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
  davisnet-datalogger/      ← Static control topics — OPTIONAL manual rain correction
    set_daily_rain            (Davis's own rain fields are computed standalone
    set_rain_rate              from its RF tip counter; nothing depends on these)
  airlink-<did>/            ← Davis AirLink air quality sensor
    observation
  aqmonitor-<id>/           ← Custom Air Quality Monitor (ESPHome, field-compatible with AirLink)
    observation
  meteobridge-<mac>/        ← Meteobridge (optional)
    observation
```

Meteobridge (`weatherdatalogger/meteobridge/`) is a full station like any other — `station_roles` (see `weatherdatalogger/database/`) decides which physical station actually supplies each field of `combined_realtime` when more than one reports the same kind of reading.

---

## Installation (Debian / Proxmox LXC)

Run as root on a fresh host:

```bash
curl -fsSL https://raw.githubusercontent.com/briis/WeatherDatalogger/main/weatherdatalogger/scripts/install.sh -o install.sh
sudo bash install.sh
```

This one command:
1. Installs OS prerequisites (`python3`, `mariadb-server`, `git`, `mosquitto-clients`)
2. Creates the `weatherdatalogger` service user
3. Installs all service files, Python virtual environments, and systemd units (via `deploy.sh`)
4. Configures MariaDB for network access and enables its event scheduler
5. Creates the database and application user — the database password is generated automatically, you never have to type or copy one
6. Creates the database schema
7. Walks you through a short setup wizard — your MQTT broker, and which stations/forecast provider you have — and writes `config.ini` for you
8. Optionally creates a read-only database user for the [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) Home Assistant integration, if you tell it you're using that
9. Enables and starts whichever services you just configured

```
==> MQTT broker hostname or IP: 192.168.1.12
==> Are you using Home Assistant? [y/N]: y
==> Do you have a WeatherFlow Tempest? [y/N]: y
    Station elevation above sea level in metres [0]: 42
==> Do you have a Davis AirLink? [y/N]: n
==> Do you have a Meteobridge? [y/N]: n
==> Enable Visual Crossing weather forecast? [y/N]: y
    Visual Crossing API key: ****************
    Forecast location latitude: 55.737406
    Forecast location longitude: 12.165889
==> Will you be installing the WeatherDatalogger-HA integration? [y/N]: y
    Password for the read-only 'weatherdatalogger_ha' database user: ****************
```

It's safe to re-run `sudo bash /opt/weatherdatalogger/scripts/install.sh` anytime — the OS/MariaDB/database steps just verify and skip once already done, and the wizard is skipped entirely if `config.ini` already exists (so it's never overwritten). To change your setup later, edit `/opt/weatherdatalogger/config.ini` directly and run `deploy.sh` (see [Updating](#updating)) — flip a service's `enabled` flag and it's enabled and started automatically on the next deploy.

**Adding the [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) integration later?** It needs a read-only database user, which the install wizard only offers to create at first-time setup. Create it anytime with:

```bash
sudo bash /opt/weatherdatalogger/scripts/create_ha_readonly_user.sh
```

Safe to re-run — if the user already exists it leaves it (and its password) alone rather than resetting anything.

On the first observation you should see a `Registered station` line in the DB writer log (`journalctl -u weatherdb-writer -f`), then `Wrote … @ …` every 10–15 s.

> `systemctl enable`/`disable` and `config.ini`'s `enabled` flag are
> independent — a service can be systemd-enabled (starts on boot) yet
> config-disabled (starts, logs, and immediately idles), and vice versa.
> `deploy.sh` keeps them in sync going forward — enabling and starting
> whatever `config.ini` says should run — but it will never *disable*/stop
> a running service just because `config.ini` now says `false`; that stays
> a deliberate manual `systemctl disable --now`.

<details>
<summary><h3>Manual installation (troubleshooting / customizing)</h3></summary>

`install.sh` automates everything below — read this if you want to see or replicate the individual steps, e.g. to customize something it assumes, or to debug a step that failed.

#### 1. Install prerequisites

```bash
apt update && apt install -y python3 python3-venv git mariadb-server mosquitto-clients
```

On Debian, MariaDB is already secured by default — root access requires no password and is restricted to the system `root` user via Unix socket authentication.

#### 2. Create a dedicated service user

```bash
useradd -r -s /usr/sbin/nologin weatherdatalogger
```

#### 3. Bootstrap the deploy script

```bash
mkdir -p /opt/weatherdatalogger/scripts
curl -fsSL https://raw.githubusercontent.com/briis/WeatherDatalogger/main/weatherdatalogger/scripts/deploy.sh -o /opt/weatherdatalogger/scripts/deploy.sh
chmod +x /opt/weatherdatalogger/scripts/deploy.sh
```

#### 4. Run the deploy script (first time)

```bash
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

This clones the repo, installs all service files under `/opt/weatherdatalogger/`, creates Python virtual environments, installs dependencies, and registers the systemd unit files.

#### 5. Configure MariaDB for network access

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

#### 6. Create the database

Edit the password in the SQL script before running:

```bash
nano /opt/weatherdatalogger/database/01_create_database.sql
mariadb -u root < /opt/weatherdatalogger/database/01_create_database.sql
```

#### 7. Create the tables

```bash
mariadb -u root weatherdatalogger \
    < /opt/weatherdatalogger/database/02_create_tables.sql
```

This creates all schema objects in one step: the `stations`, `realtime`, `history`, and `history_charting` tables; the `combined_realtime` view; and the `evt_aggregate_history_charting` event.

#### 8. Enable the MariaDB event scheduler

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

#### 9. Create the shared config file

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

#### 10. Enable and start the services

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

#### 11. (Optional) Create a read-only user for the Home Assistant integration

Only needed if you're using [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA), which reads this database directly and only ever needs `SELECT`:

```bash
mysql -u root weatherdatalogger < /opt/weatherdatalogger/database/03_create_readonly_user.sql
```

Edit the password on the `CREATE USER` line before running — or skip editing SQL by hand entirely and run `sudo bash /opt/weatherdatalogger/scripts/create_ha_readonly_user.sh` instead, which prompts for the password for you.

</details>

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
- Enables and restarts each service whose `config.ini` says it should run — `enabled = true` in its own section for station/forecast services, or just `config.ini` existing at all for `weatherdb-writer` (which has no `enabled` flag of its own). A service that isn't yet systemd-enabled gets `systemctl enable`d automatically the first time its config says `true` — no more manual `systemctl enable --now` per service. It never works the other way around: a running service whose config now says `false` is skipped, not stopped — turning one off is always a deliberate `systemctl disable --now`

Check what's currently installed anytime with:

```bash
cat /opt/weatherdatalogger/VERSION
```

Include this when reporting a bug or requesting a change — it pins down exactly which commit is running. See [`CHANGELOG.md`](CHANGELOG.md) for what changed in each version.

> **Breaking change (as of 0.1.0):** Tempest, AirLink, and Meteobridge now
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
