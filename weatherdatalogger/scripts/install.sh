#!/usr/bin/env bash
# install.sh — One-time (but safely re-runnable) setup for a fresh
#              Debian-based host: OS packages, service user, MariaDB,
#              database/tables, and a short config wizard — then hands off
#              to deploy.sh for the actual service files/venvs and to
#              enable+start whichever services you configure.
#
# Run as root on a fresh host:
#   curl -fsSL https://raw.githubusercontent.com/briis/WeatherDatalogger/main/weatherdatalogger/scripts/install.sh -o install.sh
#   sudo bash install.sh
#
# What this script does:
#   1. Installs OS prerequisites (python3, mariadb-server, git, ...)
#   2. Creates the 'weatherdatalogger' service user
#   3. Fetches and runs deploy.sh (installs all service files/venvs)
#   4. Configures MariaDB for network access and enables its event scheduler
#   5. Creates the database and application user (password auto-generated)
#   6. Creates/verifies the database schema
#   7. Runs a short setup wizard — MQTT broker, which stations/forecast
#      provider you have — and writes config.ini for you
#   8. Re-runs deploy.sh, which now applies migrations and enables+starts
#      whichever services config.ini says should run
#
# Safe to re-run: every step above either no-ops or just verifies once
# already done. If config.ini already exists, the wizard is skipped
# entirely so it's never overwritten — edit it directly and re-run this
# script (or deploy.sh) to apply changes.

set -euo pipefail

RAW_DEPLOY_URL="https://raw.githubusercontent.com/briis/WeatherDatalogger/main/weatherdatalogger/scripts/deploy.sh"

INSTALL_ROOT="/opt/weatherdatalogger"
SHARED_CONFIG="$INSTALL_ROOT/config.ini"
WRITER_DIR="$INSTALL_ROOT/database"
DEPLOY_SCRIPT="$INSTALL_ROOT/scripts/deploy.sh"

SERVICE_USER="weatherdatalogger"
DB_NAME="weatherdatalogger"
DB_APP_USER="weatherlogger"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "This installer must be run as root: sudo bash install.sh" >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1; then
    echo "This installer targets Debian-based systems with systemd (needs apt-get and systemctl)." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. OS prerequisites — apt install is already a no-op for installed
#    packages, so no extra guard needed. mosquitto-clients isn't required
#    by any service itself, but it's what the docs point you at for
#    mosquitto_sub/mosquitto_pub when troubleshooting MQTT.
# ---------------------------------------------------------------------------
echo "==> Installing OS prerequisites…"
apt-get update -qq
apt-get install -y -qq python3 python3-venv git mariadb-server mosquitto-clients curl

# ---------------------------------------------------------------------------
# 2. Service user
# ---------------------------------------------------------------------------
if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "==> Service user '$SERVICE_USER' already exists."
else
    echo "==> Creating service user '$SERVICE_USER'…"
    useradd -r -s /usr/sbin/nologin "$SERVICE_USER"
fi

# ---------------------------------------------------------------------------
# 3. Bootstrap + first deploy.sh pass — installs all service files/venvs.
#    Its migration and restart steps naturally no-op this early since
#    config.ini doesn't exist yet.
# ---------------------------------------------------------------------------
mkdir -p "$INSTALL_ROOT/scripts"
if [[ ! -f "$DEPLOY_SCRIPT" ]]; then
    echo "==> Fetching deploy.sh…"
    curl -fsSL "$RAW_DEPLOY_URL" -o "$DEPLOY_SCRIPT"
    chmod +x "$DEPLOY_SCRIPT"
fi

echo "==> Running deploy.sh (first pass — installs service files)…"
bash "$DEPLOY_SCRIPT"

# ---------------------------------------------------------------------------
# 4. MariaDB — network access. Only touched if it's still the Debian
#    default (127.0.0.1); if it's already something else — including
#    already 0.0.0.0 from a prior run — leave it alone rather than
#    clobbering a custom setup.
# ---------------------------------------------------------------------------
MARIADB_CNF="/etc/mysql/mariadb.conf.d/50-server.cnf"
MARIADB_RESTART_NEEDED=false

if [[ -f "$MARIADB_CNF" ]] && grep -qE '^bind-address\s*=\s*127\.0\.0\.1' "$MARIADB_CNF"; then
    echo "==> Configuring MariaDB for network access…"
    sed -i 's/^bind-address\s*=.*/bind-address = 0.0.0.0/' "$MARIADB_CNF"
    MARIADB_RESTART_NEEDED=true
else
    echo "==> MariaDB network access already configured (or customized) — leaving $MARIADB_CNF alone."
fi

# ---------------------------------------------------------------------------
# 5. MariaDB — event scheduler (needed for the history_charting aggregation
#    event; off by default).
# ---------------------------------------------------------------------------
EVENT_CNF="/etc/mysql/mariadb.conf.d/99-local.cnf"
if grep -qiE '^event_scheduler\s*=\s*ON' "$EVENT_CNF" 2>/dev/null; then
    echo "==> MariaDB event scheduler already enabled."
else
    echo "==> Enabling the MariaDB event scheduler…"
    printf '[mysqld]\nevent_scheduler = ON\n' > "$EVENT_CNF"
    MARIADB_RESTART_NEEDED=true
fi

if [[ "$MARIADB_RESTART_NEEDED" == "true" ]]; then
    echo "==> Restarting MariaDB to apply config changes…"
    systemctl restart mariadb
fi

# ---------------------------------------------------------------------------
# 6. Database + application user. Root access needs no password on Debian
#    (Unix socket auth) — matches the project's existing manual docs.
#    Only generates/sets a password if the app user doesn't exist yet;
#    an existing user's password is never touched.
# ---------------------------------------------------------------------------
DB_USER_EXISTS=$(mariadb --silent --skip-column-names -u root -e \
    "SELECT COUNT(*) FROM mysql.user WHERE User='$DB_APP_USER';")

DB_PASSWORD=""
if [[ "$DB_USER_EXISTS" -eq 0 ]]; then
    echo "==> Creating database and application user…"
    # `|| true`: `head -c 32` closing its input early sends tr a SIGPIPE
    # once it's read enough (exit 141) — harmless (the password is already
    # fully captured by then), but `pipefail` would otherwise propagate
    # that exit code and `set -e` would abort the script right here.
    DB_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true)
    mariadb -u root -e "
        CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        CREATE USER IF NOT EXISTS '$DB_APP_USER'@'%' IDENTIFIED BY '$DB_PASSWORD';
        GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_APP_USER'@'%';
        FLUSH PRIVILEGES;
    "
else
    echo "==> Database user '$DB_APP_USER' already exists — leaving its password alone."
fi

# ---------------------------------------------------------------------------
# 7. Tables — safe to re-run every time; every statement in this file is
#    already CREATE TABLE IF NOT EXISTS.
# ---------------------------------------------------------------------------
echo "==> Creating/verifying database schema…"
mariadb -u root "$DB_NAME" < "$WRITER_DIR/02_create_tables.sql"

# ---------------------------------------------------------------------------
# 8. Config wizard — only for a brand new config.ini; an existing one is
#    never touched by this script.
#
# Applies collected answers while preserving config.example.ini's comments
# — configparser would silently strip every comment on write, which would
# defeat the whole well-commented template. Instead: read line by line,
# track the current [section], and for any "key = value" line whose
# (section, key) is targeted, replace only the value text, leaving
# indentation/comments/everything else untouched. Values arrive as
# separate argv elements (never interpolated into a shell string or
# regex), so arbitrary characters in passwords/API keys are safe.
# ---------------------------------------------------------------------------
_set_config_values() {
    local ini_path="$1"
    shift
    python3 - "$ini_path" "$@" <<'PYEOF'
import re
import sys

path = sys.argv[1]
triples = sys.argv[2:]
updates = {}
for i in range(0, len(triples), 3):
    section, key, value = triples[i], triples[i + 1], triples[i + 2]
    updates[(section, key)] = value

with open(path) as f:
    lines = f.readlines()

section_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
# Groups: leading indent, key, padding before "=", old value (discarded).
kv_re = re.compile(r"^([ \t]*)([A-Za-z0-9_]+)([ \t]*)=[ \t]*(.*)$")

current_section = None
out = []
for line in lines:
    ending = ""
    body = line
    if body.endswith("\n"):
        body = body[:-1]
        ending = "\n"
    m = section_re.match(body)
    if m:
        current_section = m.group(1)
        out.append(line)
        continue
    kv = kv_re.match(body)
    if kv and current_section is not None:
        indent, key, pad_before_eq, _old_value = kv.groups()
        if (current_section, key) in updates:
            out.append(f"{indent}{key}{pad_before_eq}= {updates[(current_section, key)]}{ending}")
            continue
    out.append(line)

with open(path, "w") as f:
    f.writelines(out)
PYEOF
}

_ask() {
    # $1 = prompt text, $2 = default (optional). Prints the answer (or
    # default if left blank) on stdout; the prompt itself goes to stderr
    # via `read -p`, so it's visible without polluting a $(...) capture.
    local prompt="$1" default="${2:-}" reply
    if [[ -n "$default" ]]; then
        read -rp "$prompt [$default]: " reply || reply=""
        echo "${reply:-$default}"
    else
        read -rp "$prompt: " reply || reply=""
        echo "$reply"
    fi
}

_ask_yn() {
    # $1 = prompt text. Prints "true" or "false"; blank/anything but y/yes = false.
    local prompt="$1" reply
    read -rp "$prompt [y/N]: " reply || reply=""
    case "$reply" in
        [Yy]|[Yy][Ee][Ss]) echo "true" ;;
        *) echo "false" ;;
    esac
}

_ask_secret() {
    # $1 = prompt text. Like _ask, but typed input isn't echoed to the
    # terminal (read -s) — for passwords/API keys.
    local prompt="$1" reply
    read -rsp "$prompt: " reply || reply=""
    echo "" >&2
    echo "$reply"
}

if [[ -f "$SHARED_CONFIG" ]]; then
    echo "==> $SHARED_CONFIG already exists — skipping setup wizard."
    echo "    Edit it directly, then re-run this script (or deploy.sh) to apply changes."
else
    echo "==> $SHARED_CONFIG not found — running first-time setup wizard."
    cp "$INSTALL_ROOT/config.example.ini" "$SHARED_CONFIG"

    echo ""
    echo "── MQTT broker ─────────────────────────────────────────────────"
    MQTT_BROKER=""
    while [[ -z "$MQTT_BROKER" ]]; do
        MQTT_BROKER=$(_ask "MQTT broker hostname or IP")
        [[ -z "$MQTT_BROKER" ]] && echo "    Required — please enter a value."
    done
    MQTT_USERNAME=$(_ask "MQTT username (leave blank if none)")
    MQTT_PASSWORD=$(_ask_secret "MQTT password (leave blank if none)")

    echo ""
    HA=$(_ask_yn "Are you using Home Assistant?")
    HA_DISCOVERY="$HA"
    MQTT_RETAIN="$HA"

    updates=(
        mqtt broker "$MQTT_BROKER"
        mqtt username "$MQTT_USERNAME"
        mqtt password "$MQTT_PASSWORD"
        mqtt retain "$MQTT_RETAIN"
        homeassistant discovery "$HA_DISCOVERY"
        database password "$DB_PASSWORD"
    )

    echo ""
    echo "── Weather stations — enable only what you own ────────────────"
    TEMPEST=$(_ask_yn "Do you have a WeatherFlow Tempest?")
    updates+=(tempest enabled "$TEMPEST")
    if [[ "$TEMPEST" == "true" ]]; then
        ELEVATION=$(_ask "Station elevation above sea level in metres" "0")
        updates+=(station elevation_m "$ELEVATION")
    fi

    AIRLINK=$(_ask_yn "Do you have a Davis AirLink?")
    updates+=(airlink enabled "$AIRLINK")
    if [[ "$AIRLINK" == "true" ]]; then
        AIRLINK_HOST=$(_ask "AirLink IP address or hostname")
        updates+=(airlink host "$AIRLINK_HOST")
    fi

    METEOBRIDGE=$(_ask_yn "Do you have a Meteobridge?")
    updates+=(meteobridge enabled "$METEOBRIDGE")
    if [[ "$METEOBRIDGE" == "true" ]]; then
        METEOBRIDGE_HOST=$(_ask "Meteobridge IP address or hostname")
        updates+=(meteobridge host "$METEOBRIDGE_HOST")
    fi

    echo ""
    echo "── Forecast provider ───────────────────────────────────────────"
    VISUALCROSSING=$(_ask_yn "Enable Visual Crossing weather forecast?")
    updates+=(visualcrossing enabled "$VISUALCROSSING")
    if [[ "$VISUALCROSSING" == "true" ]]; then
        VC_API_KEY=$(_ask_secret "Visual Crossing API key")
        VC_LAT=$(_ask "Forecast location latitude")
        VC_LON=$(_ask "Forecast location longitude")
        updates+=(
            visualcrossing api_key "$VC_API_KEY"
            visualcrossing latitude "$VC_LAT"
            visualcrossing longitude "$VC_LON"
        )
    fi

    _set_config_values "$SHARED_CONFIG" "${updates[@]}"
    echo ""
    echo "==> $SHARED_CONFIG written. Ports, intervals, timeouts, and other"
    echo "    secondary settings were left at their defaults — edit"
    echo "    $SHARED_CONFIG directly to fine-tune those."

    echo ""
    echo "── Home Assistant integration (optional) ───────────────────────"
    HA_INTEGRATION=$(_ask_yn "Will you be installing the WeatherDatalogger-HA integration (github.com/briis/WeatherDatalogger-HA)?")
    if [[ "$HA_INTEGRATION" == "true" ]]; then
        bash "$INSTALL_ROOT/scripts/create_ha_readonly_user.sh"
    else
        echo "    Skipping — run 'sudo bash $INSTALL_ROOT/scripts/create_ha_readonly_user.sh'"
        echo "    anytime later if you decide to add it."
    fi
fi

# ---------------------------------------------------------------------------
# 9. Second deploy.sh pass — config.ini now has real values, so this
#    generates db.cnf, applies pending migrations, and enables+starts
#    whichever services are now [section] enabled = true.
# ---------------------------------------------------------------------------
echo "==> Running deploy.sh (second pass — applying config, starting services)…"
bash "$DEPLOY_SCRIPT"

# ---------------------------------------------------------------------------
# 10. Summary
# ---------------------------------------------------------------------------
echo ""
echo "==> Install complete. Installed version: $(cat "$INSTALL_ROOT/VERSION" 2>/dev/null || echo unknown)"
echo "    Re-run 'sudo bash $DEPLOY_SCRIPT' anytime to update, or this"
echo "    script again — both are safe to re-run and pick up config.ini"
echo "    changes automatically."
