-- Run once on the production weatherdatalogger MariaDB host, as root, after
-- 01_create_database.sql and 02_create_tables.sql:
--   mysql -u root weatherdatalogger < /path/to/database/03_create_readonly_user.sql
--
-- Change the password on the CREATE USER line before running.
--
-- Prefer `scripts/create_ha_readonly_user.sh` over running this file by
-- hand — it prompts for the password and does the same thing, safely
-- re-runnable.
--
-- Creates a read-only user for the WeatherDatalogger-HA Home Assistant
-- integration (https://github.com/briis/WeatherDatalogger-HA). It only
-- ever SELECTs, so it doesn't need the 'weatherlogger' writer user's
-- INSERT/UPDATE privileges (see 01_create_database.sql).

CREATE USER IF NOT EXISTS 'weatherdatalogger_ha'@'%' IDENTIFIED BY 'change_me_before_running';

GRANT SELECT ON weatherdatalogger.* TO 'weatherdatalogger_ha'@'%';

FLUSH PRIVILEGES;
