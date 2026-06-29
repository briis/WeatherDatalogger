#!/usr/bin/env bash
# deploy.sh — Fetch the latest production files from GitHub, apply pending
#             database migrations, and restart the Tempest datalogger service.
#
# Run as root on the production LXC:
#   sudo bash /opt/tempest-datalogger/scripts/deploy.sh
#
# What this script does:
#   1. Clones the repo to a temporary staging directory
#   2. Copies only the files needed to run in production
#   3. Syncs the systemd unit file if it changed
#   4. Applies any pending SQL migration scripts to the database
#   5. Updates Python dependencies
#   6. Restores ownership to the 'tempest' service user
#   7. Restarts the service
#
# Files never touched: config.ini, /etc/weatherdatalogger/db.cnf
#   (your local configuration is always preserved)
#
# Database credentials are read from /etc/weatherdatalogger/db.cnf:
#   [client]
#   host     = localhost
#   database = weatherdatalogger
#   user     = weatherlogger
#   password = your_password_here

set -euo pipefail

REPO_URL="git@github.com:briis/WeatherDatalogger.git"

# Tempest datalogger
INSTALL_DIR="/opt/tempest-datalogger"
VENV="$INSTALL_DIR/venv"
SERVICE="tempest-datalogger"
SYSTEMD_TARGET="/etc/systemd/system/tempest-datalogger.service"

# WeatherDB writer
WRITER_DIR="/opt/weatherdb-writer"
WRITER_VENV="$WRITER_DIR/venv"
WRITER_SERVICE="weatherdb-writer"
WRITER_SYSTEMD_TARGET="/etc/systemd/system/weatherdb-writer.service"

DB_CNF="/etc/weatherdatalogger/db.cnf"

# ---------------------------------------------------------------------------
# Staging — always cleaned up on exit, even if the script fails
# ---------------------------------------------------------------------------
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

echo "==> Fetching latest code from GitHub…"
git clone --quiet --depth 1 --branch main "$REPO_URL" "$STAGING"

# ---------------------------------------------------------------------------
# Install only the files required for production
# ---------------------------------------------------------------------------
echo "==> Installing production files to $INSTALL_DIR…"
install -m 644 "$STAGING/tempest/tempest_datalogger.py" "$INSTALL_DIR/tempest_datalogger.py"
install -m 644 "$STAGING/tempest/requirements.txt"       "$INSTALL_DIR/requirements.txt"
install -m 644 "$STAGING/tempest/config.example.ini"     "$INSTALL_DIR/config.example.ini"
install -m 644 "$STAGING/tempest/README.md"              "$INSTALL_DIR/README.md"
install -D -m 755 "$STAGING/scripts/deploy.sh"           "$INSTALL_DIR/scripts/deploy.sh"

# Database SQL scripts — kept on disk for manual re-runs and reference
mkdir -p "$INSTALL_DIR/database/migrations"
install -m 644 "$STAGING/database/01_create_database.sql" "$INSTALL_DIR/database/01_create_database.sql"
install -m 644 "$STAGING/database/02_create_tables.sql"   "$INSTALL_DIR/database/02_create_tables.sql"
cp -a "$STAGING/database/migrations/." "$INSTALL_DIR/database/migrations/"

# ---------------------------------------------------------------------------
# Install WeatherDB writer
# ---------------------------------------------------------------------------
echo "==> Installing WeatherDB writer to $WRITER_DIR…"
install -D -m 755 "$STAGING/database/db_writer.py"          "$WRITER_DIR/db_writer.py"
install -m 644 "$STAGING/database/requirements.txt"          "$WRITER_DIR/requirements.txt"
install -m 644 "$STAGING/database/config.example.ini"        "$WRITER_DIR/config.example.ini"

# Systemd unit for DB writer
echo "==> Syncing weatherdb-writer systemd unit…"
if ! diff -q "$STAGING/database/systemd/weatherdb-writer.service" \
             "$WRITER_SYSTEMD_TARGET" >/dev/null 2>&1; then
    install -m 644 \
        "$STAGING/database/systemd/weatherdb-writer.service" \
        "$WRITER_SYSTEMD_TARGET"
    systemctl daemon-reload
    echo "    Unit file updated and daemon reloaded."
fi

# ---------------------------------------------------------------------------
# Systemd unit — reload only when the file actually changed
# ---------------------------------------------------------------------------
echo "==> Syncing systemd unit…"
if ! diff -q "$STAGING/tempest/systemd/tempest-datalogger.service" \
             "$SYSTEMD_TARGET" >/dev/null 2>&1; then
    install -m 644 \
        "$STAGING/tempest/systemd/tempest-datalogger.service" \
        "$SYSTEMD_TARGET"
    systemctl daemon-reload
    echo "    Unit file updated and daemon reloaded."
fi

# ---------------------------------------------------------------------------
# Remove dev-only files left over from a previous git clone or old deploy
# ---------------------------------------------------------------------------
echo "==> Removing dev-only files…"
rm -f \
    "$INSTALL_DIR/AGENT.md" \
    "$INSTALL_DIR/CONTEXT.md" \
    "$INSTALL_DIR/config.dev.ini" \
    "$INSTALL_DIR/requirements-dev.txt" \
    "$INSTALL_DIR/.ruff.toml" \
    "$INSTALL_DIR/.gitignore" \
    "$INSTALL_DIR/.DS_Store" \
    "$INSTALL_DIR/LICENSE" \
    "$INSTALL_DIR/WeatherDatalogger.code-workspace" \
    "$INSTALL_DIR/scripts/lint" \
    "$INSTALL_DIR/scripts/simulate_udp.py"
rm -rf \
    "$INSTALL_DIR/.git" \
    "$INSTALL_DIR/.devcontainer" \
    "$INSTALL_DIR/.ruff_cache" \
    "$INSTALL_DIR/__pycache__" \
    "$INSTALL_DIR/systemd"

# ---------------------------------------------------------------------------
# Database migrations — apply any .sql files in database/migrations/ that
# have not yet been recorded in the schema_migrations table.
# Skipped entirely if the credentials file does not exist.
# ---------------------------------------------------------------------------
if [[ -f "$DB_CNF" ]]; then
    echo "==> Checking for pending database migrations…"
    MYSQL="mysql --defaults-extra-file=$DB_CNF --silent --skip-column-names"

    # Verify the schema_migrations table exists before querying it
    TABLE_EXISTS=$($MYSQL -e "
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = 'schema_migrations';
    ")

    if [[ "$TABLE_EXISTS" -eq 1 ]]; then
        shopt -s nullglob
        for sql_file in "$INSTALL_DIR/database/migrations/"*.sql; do
            filename=$(basename "$sql_file")
            already_applied=$($MYSQL -e "
                SELECT COUNT(*) FROM schema_migrations WHERE filename = '$filename';
            ")
            if [[ "$already_applied" -eq 0 ]]; then
                echo "    Applying migration: $filename"
                $MYSQL < "$sql_file"
                $MYSQL -e "
                    INSERT INTO schema_migrations (filename) VALUES ('$filename');
                "
                echo "    Done: $filename"
            else
                echo "    Already applied: $filename"
            fi
        done
        shopt -u nullglob
    else
        echo "    schema_migrations table not found — skipping migrations."
        echo "    Run $INSTALL_DIR/database/02_create_tables.sql to initialise the schema."
    fi
else
    echo "==> No database credentials found at $DB_CNF — skipping migrations."
fi

# ---------------------------------------------------------------------------
# Virtual environments — create on first run, update packages every run
# ---------------------------------------------------------------------------
if [[ ! -d "$VENV" ]]; then
    echo "==> Creating virtual environment for tempest-datalogger…"
    python3.11 -m venv "$VENV"
fi
echo "==> Updating tempest-datalogger Python dependencies…"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

if [[ ! -d "$WRITER_VENV" ]]; then
    echo "==> Creating virtual environment for weatherdb-writer…"
    python3.11 -m venv "$WRITER_VENV"
fi
echo "==> Updating weatherdb-writer Python dependencies…"
"$WRITER_VENV/bin/pip" install --quiet --upgrade pip
"$WRITER_VENV/bin/pip" install --quiet -r "$WRITER_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# Ownership — all install dirs belong to the service user
# ---------------------------------------------------------------------------
echo "==> Setting ownership (tempest:tempest)…"
chown -R tempest:tempest "$INSTALL_DIR"
chown -R tempest:tempest "$WRITER_DIR"

# ---------------------------------------------------------------------------
# Restart services
# ---------------------------------------------------------------------------
echo "==> Restarting $SERVICE…"
systemctl restart "$SERVICE"
systemctl --no-pager status "$SERVICE"

if systemctl is-enabled --quiet "$WRITER_SERVICE" 2>/dev/null; then
    echo "==> Restarting $WRITER_SERVICE…"
    systemctl restart "$WRITER_SERVICE"
    systemctl --no-pager status "$WRITER_SERVICE"
else
    echo "==> $WRITER_SERVICE not yet enabled — skipping restart."
    echo "    To enable: systemctl enable --now $WRITER_SERVICE"
fi

echo "==> Deploy complete."
