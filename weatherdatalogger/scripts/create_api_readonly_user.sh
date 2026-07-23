#!/usr/bin/env bash
# create_api_readonly_user.sh — Creates the read-only MariaDB user the
# weatherdatalogger-api service (weatherdatalogger/api/) needs to read this
# database. SELECT-only — it never writes, unlike the 'weatherlogger'
# writer user the datalogger services themselves use, and separate from
# 'weatherdatalogger_ha' (see create_ha_readonly_user.sh) so the two
# consumers' credentials can be rotated/revoked independently.
#
# Safe to re-run: if the user already exists, this does nothing rather
# than resetting its password (same idempotency pattern install.sh uses
# for the 'weatherlogger' writer user).
#
# Run as root, either standalone (e.g. enabling the API service on an
# existing install later) or via install.sh's setup wizard:
#   sudo bash /opt/weatherdatalogger/scripts/create_api_readonly_user.sh

set -euo pipefail

DB_NAME="weatherdatalogger"
API_DB_USER="weatherdatalogger_api"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root: sudo bash create_api_readonly_user.sh" >&2
    exit 1
fi

API_USER_EXISTS=$(mariadb --silent --skip-column-names -u root -e \
    "SELECT COUNT(*) FROM mysql.user WHERE User='$API_DB_USER';")

if [[ "$API_USER_EXISTS" -ne 0 ]]; then
    echo "==> '$API_DB_USER' already exists — leaving its password alone."
    echo "    To rotate its password instead:"
    echo "    mariadb -u root -e \"ALTER USER '$API_DB_USER'@'%' IDENTIFIED BY '<new password>'; FLUSH PRIVILEGES;\""
    exit 0
fi

API_PASSWORD=""
while [[ -z "$API_PASSWORD" ]]; do
    read -rsp "Password for the read-only '$API_DB_USER' database user: " API_PASSWORD || API_PASSWORD=""
    echo "" >&2
    [[ -z "$API_PASSWORD" ]] && echo "    Required — please enter a value." >&2
done

mariadb -u root -e "
    CREATE USER IF NOT EXISTS '$API_DB_USER'@'%' IDENTIFIED BY '$API_PASSWORD';
    GRANT SELECT ON $DB_NAME.* TO '$API_DB_USER'@'%';
    FLUSH PRIVILEGES;
"

echo ""
echo "==> Read-only user '$API_DB_USER' created."
echo "    Use this username and the password you just entered as [api] db_user /"
echo "    db_password in config.ini."
