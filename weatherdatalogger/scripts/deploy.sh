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
#   3. Syncs systemd unit files and reloads the daemon if any changed
#   4. Generates /opt/weatherdatalogger/db.cnf from config.ini (DB credentials)
#   5. Applies any pending SQL migration scripts to the database
#   6. Updates Python dependencies in each virtual environment
#   7. Restores ownership to the 'tempest' service user
#   8. Restarts each service (only if it was already enabled)
#
# Files never touched:
#   /opt/weatherdatalogger/config.ini  — your local configuration is preserved

set -euo pipefail

REPO_URL="git@github.com:briis/WeatherDatalogger.git"

INSTALL_ROOT="/opt/weatherdatalogger"
SHARED_CONFIG="$INSTALL_ROOT/config.ini"
DB_CNF="$INSTALL_ROOT/db.cnf"

TEMPEST_DIR="$INSTALL_ROOT/tempest"
AIRLINK_DIR="$INSTALL_ROOT/airlink"
WRITER_DIR="$INSTALL_ROOT/database"

TEMPEST_VENV="$TEMPEST_DIR/venv"
AIRLINK_VENV="$AIRLINK_DIR/venv"
WRITER_VENV="$WRITER_DIR/venv"

TEMPEST_SERVICE="tempest-datalogger"
AIRLINK_SERVICE="airlink-datalogger"
WRITER_SERVICE="weatherdb-writer"

TEMPEST_UNIT="/etc/systemd/system/tempest-datalogger.service"
AIRLINK_UNIT="/etc/systemd/system/airlink-datalogger.service"
WRITER_UNIT="/etc/systemd/system/weatherdb-writer.service"

# ---------------------------------------------------------------------------
# Staging — always cleaned up on exit, even if the script fails
# ---------------------------------------------------------------------------
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

echo "==> Fetching latest code from GitHub…"
git clone --quiet --depth 1 --branch main "$REPO_URL" "$STAGING"
STAGING_WDL="$STAGING/weatherdatalogger"

# ---------------------------------------------------------------------------
# Create directory structure
# ---------------------------------------------------------------------------
echo "==> Creating directory structure under $INSTALL_ROOT…"
mkdir -p \
    "$TEMPEST_DIR" \
    "$AIRLINK_DIR" \
    "$WRITER_DIR/migrations" \
    "$INSTALL_ROOT/scripts"

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

# Database SQL scripts — kept on disk for manual re-runs and reference
install -m 644 "$STAGING_WDL/database/01_create_database.sql" "$WRITER_DIR/01_create_database.sql"
install -m 644 "$STAGING_WDL/database/02_create_tables.sql"   "$WRITER_DIR/02_create_tables.sql"
cp -a "$STAGING_WDL/database/migrations/." "$WRITER_DIR/migrations/"

# Shared config example and deploy script
install -m 644 "$STAGING_WDL/config.example.ini"       "$INSTALL_ROOT/config.example.ini"
install -m 755 "$STAGING_WDL/scripts/deploy.sh"        "$INSTALL_ROOT/scripts/deploy.sh"

# Davis receiver — ESPHome firmware is flashed independently (not a systemd
# service here), but its server-side helper scripts live in the repo under
# davis/ (a sibling of weatherdatalogger/, not inside it). Installed
# alongside deploy.sh rather than in its own directory since it's the only
# davis-side file that runs on the server.
install -m 755 "$STAGING/davis/scripts/set_daily_rain.sh" "$INSTALL_ROOT/scripts/set_daily_rain.sh"

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
    "$WRITER_DIR:$WRITER_VENV:$WRITER_DIR/requirements.txt"; do

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
echo "==> Setting ownership (tempest:tempest)…"
chown -R tempest:tempest "$INSTALL_ROOT"

# ---------------------------------------------------------------------------
# Restart services — only if already enabled
# ---------------------------------------------------------------------------
for service in "$TEMPEST_SERVICE" "$WRITER_SERVICE" "$AIRLINK_SERVICE"; do
    if systemctl is-enabled --quiet "$service" 2>/dev/null; then
        echo "==> Restarting $service…"
        systemctl restart "$service"
        systemctl --no-pager --lines=20 status "$service" || true
    else
        echo "==> $service not yet enabled — skipping restart."
        echo "    To enable: systemctl enable --now $service"
    fi
done

echo "==> Deploy complete."
