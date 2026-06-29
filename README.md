# WeatherDatalogger

A unified weather data pipeline that collects data from multiple weather station brands and publishes everything to a single MQTT broker under a common topic namespace (`weatherdatalogger/`). Downstream consumers — Home Assistant, databases, dashboards — subscribe to MQTT and are completely decoupled from the hardware.

---

## Services

### Station loggers (hardware → MQTT)

| Directory | Hardware | Status |
|---|---|---|
| [`tempest/`](tempest/) | WeatherFlow Tempest (UDP → MQTT) | Active |
| [`davis/`](davis/) | Davis Vantage Vue (ESP32-S3 + CC1101, ESPHome) | Active — hardware available |
| [`airlink/`](airlink/) | Davis AirLink air quality sensor (HTTP polling → MQTT) | Active |

### Infrastructure (MQTT → storage)

| Directory | Purpose | Status |
|---|---|---|
| [`database/`](database/) | WeatherDB Writer — persists observations to MariaDB | Active |

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
  forecast-<location>/      ← WeatherFlow Better Forecast REST API
    current
    forecast_hourly
    forecast_daily
  davis-<id>/               ← Davis Vantage Vue (planned)
    <sensor topics>
  airlink-<did>/            ← Davis AirLink air quality sensor
    observation
```

---

## Installation (Debian / Proxmox LXC)

### 1. Install prerequisites

```bash
apt update && apt install -y python3 python3-venv git mariadb-server
```

On Debian, MariaDB is already secured by default — root access requires no password and is restricted to the system `root` user via Unix socket authentication.

### 2. Create a dedicated service user

```bash
useradd -r -s /usr/sbin/nologin tempest
```

### 3. Bootstrap the deploy script

The deploy script is the only file needed to bootstrap. Clone the repo temporarily to get it on disk (SSH key required while the repo is private):

```bash
git clone --depth 1 git@github.com:briis/WeatherDatalogger.git /tmp/wdl-bootstrap
mkdir -p /opt/tempest-datalogger/scripts
cp /tmp/wdl-bootstrap/scripts/deploy.sh /opt/tempest-datalogger/scripts/deploy.sh
chmod +x /opt/tempest-datalogger/scripts/deploy.sh
rm -rf /tmp/wdl-bootstrap
```

> Once the repository is made public this can be replaced with a single `curl` command.

### 4. Run the deploy script (first time)

```bash
sudo bash /opt/tempest-datalogger/scripts/deploy.sh
```

This clones the repo, installs all production files (including SQL scripts and the DB writer), creates Python virtual environments, installs dependencies, and registers the systemd unit files. Database migrations are skipped on this first run because the credentials file does not exist yet.

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

### 9. Configure and enable the WeatherDB writer

See [database/README.md](database/README.md) for full configuration details.

```bash
cp /opt/weatherdb-writer/config.example.ini /opt/weatherdb-writer/config.ini
nano /opt/weatherdb-writer/config.ini
systemctl enable --now weatherdb-writer
journalctl -u weatherdb-writer -f
```

### 10. Configure and enable the Tempest datalogger

See [tempest/README.md](tempest/README.md) for full configuration details.

```bash
cp /opt/tempest-datalogger/config.example.ini /opt/tempest-datalogger/config.ini
nano /opt/tempest-datalogger/config.ini
systemctl enable --now tempest-datalogger
journalctl -u tempest-datalogger -f
```

---

## Updating

```bash
sudo bash /opt/tempest-datalogger/scripts/deploy.sh
```

The deploy script:
- Clones the latest code from GitHub to a temporary staging directory
- Updates all production files for every service
- Applies any pending SQL migrations to the database
- Updates Python dependencies in each virtual environment
- Syncs systemd unit files and reloads the daemon if changed
- Restarts the Tempest datalogger; restarts the DB writer if it is enabled

`config.ini` files are never touched — your local configuration is always preserved.

---

## Development

Shared tooling lives at the repo root and applies to all services:

```bash
bash scripts/lint        # ruff format + ruff check --fix (all Python in repo)
```

Requirements: `pip install -r requirements-dev.txt`
