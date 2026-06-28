#!/usr/bin/env bash
# deploy.sh — Fetch the latest production files from GitHub and restart the service.
#
# Run as root on the production LXC:
#   sudo bash /opt/tempest-datalogger/scripts/deploy.sh
#
# What this script does:
#   1. Clones the repo to a temporary staging directory
#   2. Copies only the files needed to run in production
#   3. Syncs the systemd unit file if it changed
#   4. Updates Python dependencies
#   5. Restores ownership to the 'tempest' service user
#   6. Restarts the service
#
# Files never touched: config.ini  (your local configuration is always preserved)

set -euo pipefail

REPO_URL="https://github.com/briis/tempest-weatherdatalogger.git"
INSTALL_DIR="/opt/tempest-datalogger"
VENV="$INSTALL_DIR/venv"
SERVICE="tempest-datalogger"
SYSTEMD_TARGET="/etc/systemd/system/tempest-datalogger.service"

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
install -m 644 "$STAGING/tempest_datalogger.py" "$INSTALL_DIR/tempest_datalogger.py"
install -m 644 "$STAGING/requirements.txt"       "$INSTALL_DIR/requirements.txt"
install -m 644 "$STAGING/config.example.ini"     "$INSTALL_DIR/config.example.ini"
install -m 644 "$STAGING/README.md"              "$INSTALL_DIR/README.md"
install -D -m 755 "$STAGING/scripts/deploy.sh"   "$INSTALL_DIR/scripts/deploy.sh"

# ---------------------------------------------------------------------------
# Systemd unit — reload only when the file actually changed
# ---------------------------------------------------------------------------
echo "==> Syncing systemd unit…"
if ! diff -q "$STAGING/systemd/tempest-datalogger.service" \
             "$SYSTEMD_TARGET" >/dev/null 2>&1; then
    install -m 644 \
        "$STAGING/systemd/tempest-datalogger.service" \
        "$SYSTEMD_TARGET"
    systemctl daemon-reload
    echo "    Unit file updated and daemon reloaded."
fi

# ---------------------------------------------------------------------------
# Virtual environment — create on first run, update packages every run
# ---------------------------------------------------------------------------
if [[ ! -d "$VENV" ]]; then
    echo "==> Creating virtual environment…"
    python3.11 -m venv "$VENV"
fi

echo "==> Updating Python dependencies…"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# Ownership — everything in INSTALL_DIR belongs to the service user
# ---------------------------------------------------------------------------
echo "==> Setting ownership (tempest:tempest)…"
chown -R tempest:tempest "$INSTALL_DIR"

# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------
echo "==> Restarting $SERVICE…"
systemctl restart "$SERVICE"
systemctl --no-pager status "$SERVICE"

echo "==> Deploy complete."
