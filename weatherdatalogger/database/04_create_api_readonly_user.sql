-- Run once on the production weatherdatalogger MariaDB host, as root, after
-- 01_create_database.sql and 02_create_tables.sql:
--   mysql -u root weatherdatalogger < /path/to/database/04_create_api_readonly_user.sql
--
-- Change the password on the CREATE USER line before running.
--
-- Prefer `scripts/create_api_readonly_user.sh` over running this file by
-- hand — it prompts for the password and does the same thing, safely
-- re-runnable.
--
-- Creates a read-only user for the weatherdatalogger-api service
-- (weatherdatalogger/api/). It only ever SELECTs, so it doesn't need the
-- 'weatherlogger' writer user's INSERT/UPDATE privileges (see
-- 01_create_database.sql) — separate from 'weatherdatalogger_ha' (see
-- 03_create_readonly_user.sql) so the two consumers' credentials can be
-- rotated/revoked independently.

CREATE USER IF NOT EXISTS 'weatherdatalogger_api'@'%' IDENTIFIED BY 'change_me_before_running';

GRANT SELECT ON weatherdatalogger.* TO 'weatherdatalogger_api'@'%';

FLUSH PRIVILEGES;
