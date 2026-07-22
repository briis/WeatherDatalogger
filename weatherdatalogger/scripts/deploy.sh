#!/usr/bin/env bash
# deploy.sh — Fetch the latest production files from GitHub, apply pending
#             database migrations, and restart all enabled services.
#
# Run as root on the production LXC:
#   sudo bash /opt/weatherdatalogger/scripts/deploy.sh
#
# What this script does:
#   1. Clones the repo to a temporary staging directory
#   2. Installs all service files under /opt/weatherdatalogger/
#   3. Records the installed version (repo's VERSION file + commit SHA) to
#      /opt/weatherdatalogger/VERSION — `cat` it anytime to check what's
#      installed; report it when asking for a change or filing an issue
#   4. Syncs systemd unit files and reloads the daemon if any changed
#   5. Generates /opt/weatherdatalogger/db.cnf from config.ini (DB credentials)
#   6. Applies any pending SQL migration scripts to the database
#   7. Updates Python dependencies in each virtual environment
#   8. Restores ownership to the 'weatherdatalogger' service user
#   9. Enables (if needed) and restarts each service whose config.ini says
#      it should run — [section] enabled = true for station/forecast
#      services, or "config.ini exists at all" for weatherdb-writer (which
#      has no enabled flag of its own). Never auto-disables/stops a
#      service just because config now says false — that stays a manual
#      `systemctl disable --now`
#
# Files never touched:
#   /opt/weatherdatalogger/config.ini  — your local configuration is preserved

set -euo pipefail

REPO_URL="https://github.com/briis/WeatherDatalogger.git"

INSTALL_ROOT="/opt/weatherdatalogger"
SHARED_CONFIG="$INSTALL_ROOT/config.ini"
DB_CNF="$INSTALL_ROOT/db.cnf"
LOG_DIR="/var/log/weatherdatalogger"

TEMPEST_DIR="$INSTALL_ROOT/tempest"
AIRLINK_DIR="$INSTALL_ROOT/airlink"
WRITER_DIR="$INSTALL_ROOT/database"
METEOBRIDGE_DIR="$INSTALL_ROOT/meteobridge"
VISUALCROSSING_DIR="$INSTALL_ROOT/visualcrossing"

TEMPEST_VENV="$TEMPEST_DIR/venv"
AIRLINK_VENV="$AIRLINK_DIR/venv"
WRITER_VENV="$WRITER_DIR/venv"
METEOBRIDGE_VENV="$METEOBRIDGE_DIR/venv"
VISUALCROSSING_VENV="$VISUALCROSSING_DIR/venv"

TEMPEST_SERVICE="tempest-datalogger"
AIRLINK_SERVICE="airlink-datalogger"
WRITER_SERVICE="weatherdb-writer"
METEOBRIDGE_SERVICE="meteobridge-datalogger"
VISUALCROSSING_SERVICE="visualcrossing-datalogger"

TEMPEST_UNIT="/etc/systemd/system/tempest-datalogger.service"
AIRLINK_UNIT="/etc/systemd/system/airlink-datalogger.service"
WRITER_UNIT="/etc/systemd/system/weatherdb-writer.service"
METEOBRIDGE_UNIT="/etc/systemd/system/meteobridge-datalogger.service"
VISUALCROSSING_UNIT="/etc/systemd/system/visualcrossing-datalogger.service"

# ---------------------------------------------------------------------------
# Staging — always cleaned up on exit, even if the script fails
# ---------------------------------------------------------------------------
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

echo "==> Fetching latest code from GitHub…"
git clone --quiet --depth 1 --branch main "$REPO_URL" "$STAGING"
STAGING_WDL="$STAGING/weatherdatalogger"

# Self-update: if deploy.sh changed upstream, install the new copy and
# re-exec it now. Otherwise the rest of *this* run keeps executing the old
# script's logic/paths against a repo checkout that may have moved on
# structurally (e.g. a file relocated to a new directory) — that fails
# partway through instead of just picking up the fix, and strands the
# install on a broken deploy.sh until someone notices and refetches it by
# hand. Skips cleanly on the very first run, when there's nothing installed
# yet to compare against.
DEPLOY_SELF="$INSTALL_ROOT/scripts/deploy.sh"
if [[ -f "$DEPLOY_SELF" ]] && ! cmp -s "$STAGING_WDL/scripts/deploy.sh" "$DEPLOY_SELF"; then
    echo "==> deploy.sh changed upstream — updating and re-running…"
    install -m 755 "$STAGING_WDL/scripts/deploy.sh" "$DEPLOY_SELF"
    trap - EXIT
    rm -rf "$STAGING"
    exec bash "$DEPLOY_SELF" "$@"
fi

# Version = VERSION file (bumped by hand on meaningful changes) + the short
# commit SHA of what was actually cloned, so a user reporting an issue can
# give you an identifier that's both human-friendly and exact.
REPO_VERSION=$(cat "$STAGING/VERSION" 2>/dev/null || echo "0.0.0")
REPO_SHA=$(git -C "$STAGING" rev-parse --short HEAD)
INSTALLED_VERSION="$REPO_VERSION ($REPO_SHA)"
echo "==> Deploying WeatherDatalogger $INSTALLED_VERSION"

# ---------------------------------------------------------------------------
# Create directory structure
# ---------------------------------------------------------------------------
echo "==> Creating directory structure under $INSTALL_ROOT…"
mkdir -p \
    "$TEMPEST_DIR" \
    "$AIRLINK_DIR" \
    "$WRITER_DIR/migrations" \
    "$METEOBRIDGE_DIR" \
    "$VISUALCROSSING_DIR" \
    "$INSTALL_ROOT/scripts"

# Persistent log directory — outside INSTALL_ROOT (survives /tmp being
# cleared on reboot or by systemd-tmpfiles-clean) for services whose
# config.ini points [logging] file at it.
echo "==> Creating persistent log directory $LOG_DIR…"
mkdir -p "$LOG_DIR"
chown weatherdatalogger:weatherdatalogger "$LOG_DIR"

# ---------------------------------------------------------------------------
# Install service files
# ---------------------------------------------------------------------------
echo "==> Installing tempest-datalogger…"
install -m 755 "$STAGING_WDL/tempest/tempest_datalogger.py" "$TEMPEST_DIR/tempest_datalogger.py"
install -m 644 "$STAGING_WDL/tempest/requirements.txt"       "$TEMPEST_DIR/requirements.txt"

echo "==> Installing airlink-datalogger…"
install -m 755 "$STAGING_WDL/airlink/airlink_datalogger.py" "$AIRLINK_DIR/airlink_datalogger.py"
install -m 644 "$STAGING_WDL/airlink/requirements.txt"       "$AIRLINK_DIR/requirements.txt"

echo "==> Installing weatherdb-writer…"
install -m 755 "$STAGING_WDL/database/db_writer.py"          "$WRITER_DIR/db_writer.py"
install -m 644 "$STAGING_WDL/database/requirements.txt"      "$WRITER_DIR/requirements.txt"

echo "==> Installing meteobridge-datalogger…"
install -m 755 "$STAGING_WDL/meteobridge/meteobridge_datalogger.py" "$METEOBRIDGE_DIR/meteobridge_datalogger.py"
install -m 644 "$STAGING_WDL/meteobridge/requirements.txt"          "$METEOBRIDGE_DIR/requirements.txt"

echo "==> Installing visualcrossing-datalogger…"
install -m 755 "$STAGING_WDL/visualcrossing/visualcrossing_datalogger.py" "$VISUALCROSSING_DIR/visualcrossing_datalogger.py"
install -m 644 "$STAGING_WDL/visualcrossing/requirements.txt"             "$VISUALCROSSING_DIR/requirements.txt"

# Database SQL scripts — kept on disk for manual re-runs and reference
install -m 644 "$STAGING_WDL/database/01_create_database.sql"    "$WRITER_DIR/01_create_database.sql"
install -m 644 "$STAGING_WDL/database/02_create_tables.sql"      "$WRITER_DIR/02_create_tables.sql"
install -m 644 "$STAGING_WDL/database/03_create_readonly_user.sql" "$WRITER_DIR/03_create_readonly_user.sql"
cp -a "$STAGING_WDL/database/migrations/." "$WRITER_DIR/migrations/"

# Shared config example and scripts
install -m 644 "$STAGING_WDL/config.example.ini"                 "$INSTALL_ROOT/config.example.ini"
install -m 755 "$STAGING_WDL/scripts/deploy.sh"                  "$INSTALL_ROOT/scripts/deploy.sh"
install -m 755 "$STAGING_WDL/scripts/install.sh"                 "$INSTALL_ROOT/scripts/install.sh"
install -m 755 "$STAGING_WDL/scripts/create_ha_readonly_user.sh" "$INSTALL_ROOT/scripts/create_ha_readonly_user.sh"

# Installed version — persisted so it can be checked anytime later without
# re-running deploy.sh: `cat /opt/weatherdatalogger/VERSION`. Report this
# when asking for a change or filing an issue.
echo "$INSTALLED_VERSION" > "$INSTALL_ROOT/VERSION"

# Davis receiver — ESPHome firmware is flashed independently (not a systemd
# service here), but its server-side helper scripts live in the repo under
# ESPHome/davis/ (a sibling of weatherdatalogger/, not inside it). Installed
# alongside deploy.sh rather than in its own directory since it's the only
# davis-side file that runs on the server.
install -m 755 "$STAGING/ESPHome/davis/scripts/set_daily_rain.sh" "$INSTALL_ROOT/scripts/set_daily_rain.sh"

# ---------------------------------------------------------------------------
# Systemd units — reload only when a file actually changed
# ---------------------------------------------------------------------------
echo "==> Syncing systemd unit files…"

_sync_unit() {
    local src="$1" dst="$2"
    if ! diff -q "$src" "$dst" >/dev/null 2>&1; then
        install -m 644 "$src" "$dst"
        systemctl daemon-reload
        echo "    Updated: $(basename "$dst")"
    fi
}

_sync_unit "$STAGING_WDL/tempest/systemd/tempest-datalogger.service"  "$TEMPEST_UNIT"
_sync_unit "$STAGING_WDL/airlink/systemd/airlink-datalogger.service"  "$AIRLINK_UNIT"
_sync_unit "$STAGING_WDL/database/systemd/weatherdb-writer.service"   "$WRITER_UNIT"
_sync_unit "$STAGING_WDL/meteobridge/systemd/meteobridge-datalogger.service" "$METEOBRIDGE_UNIT"
_sync_unit "$STAGING_WDL/visualcrossing/systemd/visualcrossing-datalogger.service" "$VISUALCROSSING_UNIT"

# ---------------------------------------------------------------------------
# Shared config — print instructions on first deploy, never overwrite
# ---------------------------------------------------------------------------
if [[ ! -f "$SHARED_CONFIG" ]]; then
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────────┐"
    echo "  │  First-time setup: create the shared config file               │"
    echo "  │                                                                 │"
    echo "  │  cp $INSTALL_ROOT/config.example.ini \\"
    echo "  │     $SHARED_CONFIG"
    echo "  │  nano $SHARED_CONFIG                                            │"
    echo "  │                                                                 │"
    echo "  │  Required fields: [mqtt] broker, [airlink] host,               │"
    echo "  │                   [database] password                           │"
    echo "  └─────────────────────────────────────────────────────────────────┘"
    echo ""
fi

# ---------------------------------------------------------------------------
# db.cnf — generate from shared config so migrations can run via mysql client
# ---------------------------------------------------------------------------
if [[ -f "$SHARED_CONFIG" ]]; then
    echo "==> Generating $DB_CNF from shared config…"
    python3 - <<'PYEOF' "$SHARED_CONFIG" "$DB_CNF"
import configparser, sys
src, dst = sys.argv[1], sys.argv[2]
c = configparser.ConfigParser()
c.read(src)
db = c["database"] if "database" in c else {}
with open(dst, "w") as f:
    f.write("[client]\n")
    f.write(f"host     = {db.get('host', 'localhost')}\n")
    f.write(f"database = {db.get('name', 'weatherdatalogger')}\n")
    f.write(f"user     = {db.get('user', 'weatherlogger')}\n")
    f.write(f"password = {db.get('password', '')}\n")
import os, stat
os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR)
PYEOF
fi

# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------
if [[ -f "$DB_CNF" ]]; then
    echo "==> Checking for pending database migrations…"
    MYSQL="mysql --defaults-extra-file=$DB_CNF --silent --skip-column-names"

    TABLE_EXISTS=$($MYSQL -e "
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = 'schema_migrations';
    ")

    if [[ "$TABLE_EXISTS" -eq 1 ]]; then
        shopt -s nullglob
        for sql_file in "$WRITER_DIR/migrations/"*.sql; do
            filename=$(basename "$sql_file")
            already_applied=$($MYSQL -e "
                SELECT COUNT(*) FROM schema_migrations WHERE filename = '$filename';
            ")
            if [[ "$already_applied" -eq 0 ]]; then
                echo "    Applying migration: $filename"
                $MYSQL < "$sql_file"
                $MYSQL -e "INSERT INTO schema_migrations (filename) VALUES ('$filename');"
                echo "    Done: $filename"
            else
                echo "    Already applied: $filename"
            fi
        done
        shopt -u nullglob
    else
        echo "    schema_migrations table not found — skipping migrations."
        echo "    Run $WRITER_DIR/02_create_tables.sql to initialise the schema."
    fi
else
    echo "==> No db.cnf found — skipping migrations."
    echo "    Migrations will run automatically once config.ini is configured."
fi

# ---------------------------------------------------------------------------
# Virtual environments — create on first run, update packages every run
# ---------------------------------------------------------------------------
for dir_venv_req in \
    "$TEMPEST_DIR:$TEMPEST_VENV:$TEMPEST_DIR/requirements.txt" \
    "$AIRLINK_DIR:$AIRLINK_VENV:$AIRLINK_DIR/requirements.txt" \
    "$WRITER_DIR:$WRITER_VENV:$WRITER_DIR/requirements.txt" \
    "$METEOBRIDGE_DIR:$METEOBRIDGE_VENV:$METEOBRIDGE_DIR/requirements.txt" \
    "$VISUALCROSSING_DIR:$VISUALCROSSING_VENV:$VISUALCROSSING_DIR/requirements.txt"; do

    IFS=: read -r svc_dir venv req <<< "$dir_venv_req"
    svc_name=$(basename "$svc_dir")

    if [[ ! -d "$venv" ]]; then
        echo "==> Creating virtual environment for $svc_name…"
        python3 -m venv "$venv"
    fi
    echo "==> Updating $svc_name Python dependencies…"
    "$venv/bin/pip" install --quiet --upgrade pip
    "$venv/bin/pip" install --quiet -r "$req"
done

# ---------------------------------------------------------------------------
# Ownership — everything under the install root belongs to the service user
# ---------------------------------------------------------------------------
echo "==> Setting ownership (weatherdatalogger:weatherdatalogger)…"
chown -R weatherdatalogger:weatherdatalogger "$INSTALL_ROOT"

# ---------------------------------------------------------------------------
# Enable/restart services — config-driven. [section] enabled = true means
# "this should be running", so make it so: systemctl-enable it if it isn't
# already, then restart, regardless of prior systemd state. Never the
# reverse — if config says false (or, for weatherdb-writer, config.ini
# doesn't exist yet), a currently-running service is left alone rather than
# stopped. That keeps this script from ever surprising anyone by taking
# something down; turning a service off is a deliberate manual
# `systemctl disable --now`.
# ---------------------------------------------------------------------------

# Mirrors the db.cnf generation above: shells out to Python/configparser
# rather than hand-parsing INI in bash. fallback=False covers both "no
# config.ini yet" and "section/key not present" (e.g. a config.ini that
# predates the enabled flag) the same way each service's own DEFAULT_CONFIG
# does.
_config_enabled() {
    local section="$1"
    [[ -f "$SHARED_CONFIG" ]] || return 1
    local value
    value=$(python3 - "$SHARED_CONFIG" "$section" <<'PYEOF'
import configparser, sys
path, section = sys.argv[1], sys.argv[2]
c = configparser.ConfigParser()
c.read(path)
print(c.getboolean(section, "enabled", fallback=False))
PYEOF
)
    [[ "$value" == "True" ]]
}

# service:config-section pairs — empty section (weatherdb-writer) has no
# `enabled` flag of its own; "config.ini exists at all" is its readiness
# gate instead (it needs [database] credentials to do anything useful, and
# db_writer.py exits cleanly if --config doesn't exist, but there's no
# reason to hit that path on a fresh install before config.ini is set up).
for service_section in \
    "$TEMPEST_SERVICE:tempest" \
    "$WRITER_SERVICE:" \
    "$AIRLINK_SERVICE:airlink" \
    "$METEOBRIDGE_SERVICE:meteobridge" \
    "$VISUALCROSSING_SERVICE:visualcrossing"; do

    IFS=: read -r service section <<< "$service_section"

    should_run=false
    if [[ -n "$section" ]]; then
        _config_enabled "$section" && should_run=true
        reason="[$section] enabled is not true in config.ini"
    else
        [[ -f "$SHARED_CONFIG" ]] && should_run=true
        reason="config.ini does not exist yet"
    fi

    if [[ "$should_run" != "true" ]]; then
        if systemctl is-enabled --quiet "$service" 2>/dev/null; then
            echo "==> $service is systemd-enabled but $reason — leaving it running as-is (not auto-stopping). Run 'systemctl disable --now $service' if that's not intended."
        else
            echo "==> $service not enabled ($reason) — skipping."
        fi
        continue
    fi

    if ! systemctl is-enabled --quiet "$service" 2>/dev/null; then
        echo "==> Enabling $service…"
        systemctl enable --quiet "$service"
    fi

    echo "==> Restarting $service…"
    systemctl restart "$service"
    systemctl --no-pager --lines=20 status "$service" || true
done

echo "==> Deploy complete. Installed version: $INSTALLED_VERSION"
