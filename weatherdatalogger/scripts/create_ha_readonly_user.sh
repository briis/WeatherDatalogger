#!/usr/bin/env bash
# create_ha_readonly_user.sh — Creates the read-only MariaDB user the
# WeatherDatalogger-HA Home Assistant integration
# (https://github.com/briis/WeatherDatalogger-HA) needs to read this
# database. SELECT-only — it never writes, unlike the 'weatherlogger'
# writer user the datalogger services themselves use.
#
# Safe to re-run: if the user already exists, this does nothing rather
# than resetting its password (same idempotency pattern install.sh uses
# for the 'weatherlogger' writer user).
#
# Run as root, either standalone (e.g. adding the HA integration to an
# existing install later) or via install.sh's setup wizard:
#   sudo bash /opt/weatherdatalogger/scripts/create_ha_readonly_user.sh

set -euo pipefail

DB_NAME="weatherdatalogger"
HA_DB_USER="weatherdatalogger_ha"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root: sudo bash create_ha_readonly_user.sh" >&2
    exit 1
fi

HA_USER_EXISTS=$(mariadb --silent --skip-column-names -u root -e \
    "SELECT COUNT(*) FROM mysql.user WHERE User='$HA_DB_USER';")

if [[ "$HA_USER_EXISTS" -ne 0 ]]; then
    echo "==> '$HA_DB_USER' already exists — leaving its password alone."
    echo "    To rotate its password instead:"
    echo "    mariadb -u root -e \"ALTER USER '$HA_DB_USER'@'%' IDENTIFIED BY '<new password>'; FLUSH PRIVILEGES;\""
    exit 0
fi

HA_PASSWORD=""
while [[ -z "$HA_PASSWORD" ]]; do
    read -rsp "Password for the read-only '$HA_DB_USER' database user: " HA_PASSWORD || HA_PASSWORD=""
    echo "" >&2
    [[ -z "$HA_PASSWORD" ]] && echo "    Required — please enter a value." >&2
done

mariadb -u root -e "
    CREATE USER IF NOT EXISTS '$HA_DB_USER'@'%' IDENTIFIED BY '$HA_PASSWORD';
    GRANT SELECT ON $DB_NAME.* TO '$HA_DB_USER'@'%';
    FLUSH PRIVILEGES;
"

echo ""
echo "==> Read-only user '$HA_DB_USER' created."
echo "    Use this username and the password you just entered when configuring"
echo "    the WeatherDatalogger-HA integration (github.com/briis/WeatherDatalogger-HA)."
