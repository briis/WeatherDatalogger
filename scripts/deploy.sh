#!/usr/bin/env bash
# deploy.sh — Pull latest code from GitHub and restart the service.
#
# Run as root (or a user with sudo access to systemctl) on the production LXC:
#   sudo bash /opt/tempest-datalogger/scripts/deploy.sh
#
# Assumptions:
#   - Repo is cloned at /opt/tempest-datalogger
#   - venv lives at /opt/tempest-datalogger/venv
#   - systemd unit is tempest-datalogger.service
#   - config.ini is already in place (not overwritten by this script)

set -euo pipefail

INSTALL_DIR="/opt/tempest-datalogger"
VENV="$INSTALL_DIR/venv"
SERVICE="tempest-datalogger"
SYSTEMD_UNIT="$INSTALL_DIR/systemd/tempest-datalogger.service"
SYSTEMD_TARGET="/etc/systemd/system/tempest-datalogger.service"

echo "==> Pulling latest code from GitHub…"
git -C "$INSTALL_DIR" fetch --tags origin
git -C "$INSTALL_DIR" pull --ff-only origin main

echo "==> Installing / updating Python dependencies…"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "==> Syncing systemd unit file…"
if ! diff -q "$SYSTEMD_UNIT" "$SYSTEMD_TARGET" > /dev/null 2>&1; then
    cp "$SYSTEMD_UNIT" "$SYSTEMD_TARGET"
    systemctl daemon-reload
    echo "    Unit file updated and daemon reloaded."
fi

echo "==> Restarting $SERVICE…"
systemctl restart "$SERVICE"
systemctl --no-pager status "$SERVICE"

echo "==> Deploy complete."
