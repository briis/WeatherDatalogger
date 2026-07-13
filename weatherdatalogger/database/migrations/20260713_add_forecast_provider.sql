-- Migration: 20260713_add_forecast_provider.sql
-- Adds a `provider` dimension to forecast_current/forecast_hourly/
-- forecast_daily so a second forecast provider (e.g. Pirate Weather,
-- WeatherFlow Better Forecast) can coexist with Visual Crossing against the
-- same `location` without colliding — previously these tables assumed
-- Visual Crossing would be the only forecast source and were keyed on
-- `location` alone. See visualcrossing_datalogger.py's FORECAST_PROVIDER
-- constant and the new forecast-<provider>-<location> MQTT topic shape.
--
-- 100% of existing rows were written by Visual Crossing, so the new column
-- backfills with DEFAULT 'visualcrossing' — kept permanently (every writer
-- path always supplies an explicit value going forward, so it never fires
-- again; not worth a second ALTER just to drop it for cosmetic parity with
-- a fresh install).
--
-- The primary key / unique key swaps below can't rely on a plain
-- `DROP PRIMARY KEY` / `DROP INDEX` the way this project's `ADD COLUMN IF
-- NOT EXISTS` migrations normally achieve idempotency: deploy.sh runs each
-- migration file under `set -euo pipefail`, so a later statement failing
-- mid-file means this file is never recorded in `schema_migrations`, and a
-- re-run replays the whole file from the top — a bare DROP PRIMARY KEY/DROP
-- INDEX would then fail on a key that's already gone. Instead: combine
-- drop+add into one ALTER TABLE statement (no keyless window in between),
-- and guard each one with an INFORMATION_SCHEMA check so a retried run is a
-- no-op instead of an error.

USE weatherdatalogger;

ALTER TABLE forecast_current
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'visualcrossing' COMMENT 'Forecast provider slug, e.g. visualcrossing — matches the MQTT topic segment forecast-<provider>-<location>' FIRST;

ALTER TABLE forecast_hourly
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'visualcrossing' COMMENT 'Forecast provider slug, e.g. visualcrossing — matches the MQTT topic segment forecast-<provider>-<location>' AFTER id;

ALTER TABLE forecast_daily
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'visualcrossing' COMMENT 'Forecast provider slug, e.g. visualcrossing — matches the MQTT topic segment forecast-<provider>-<location>' AFTER id;

-- forecast_current: PRIMARY KEY (location) -> PRIMARY KEY (provider, location)
SET @has_pk = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE table_schema = DATABASE() AND table_name = 'forecast_current'
      AND constraint_type = 'PRIMARY KEY'
);
SET @pk_has_provider = (
    SELECT COUNT(*) FROM information_schema.key_column_usage
    WHERE table_schema = DATABASE() AND table_name = 'forecast_current'
      AND constraint_name = 'PRIMARY' AND column_name = 'provider'
);
SET @sql = CASE
    WHEN @pk_has_provider > 0 THEN 'SELECT 1'
    WHEN @has_pk > 0 THEN 'ALTER TABLE forecast_current DROP PRIMARY KEY, ADD PRIMARY KEY (provider, location)'
    ELSE 'ALTER TABLE forecast_current ADD PRIMARY KEY (provider, location)'
END;
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- forecast_hourly: UNIQUE KEY uq_forecast_hourly (location, forecast_time) -> (provider, location, forecast_time)
SET @has_idx = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'forecast_hourly' AND index_name = 'uq_forecast_hourly'
);
SET @idx_has_provider = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'forecast_hourly'
      AND index_name = 'uq_forecast_hourly' AND column_name = 'provider'
);
SET @sql = CASE
    WHEN @idx_has_provider > 0 THEN 'SELECT 1'
    WHEN @has_idx > 0 THEN 'ALTER TABLE forecast_hourly DROP INDEX uq_forecast_hourly, ADD UNIQUE KEY uq_forecast_hourly (provider, location, forecast_time)'
    ELSE 'ALTER TABLE forecast_hourly ADD UNIQUE KEY uq_forecast_hourly (provider, location, forecast_time)'
END;
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- forecast_daily: UNIQUE KEY uq_forecast_daily (location, forecast_time) -> (provider, location, forecast_time)
SET @has_idx = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'forecast_daily' AND index_name = 'uq_forecast_daily'
);
SET @idx_has_provider = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'forecast_daily'
      AND index_name = 'uq_forecast_daily' AND column_name = 'provider'
);
SET @sql = CASE
    WHEN @idx_has_provider > 0 THEN 'SELECT 1'
    WHEN @has_idx > 0 THEN 'ALTER TABLE forecast_daily DROP INDEX uq_forecast_daily, ADD UNIQUE KEY uq_forecast_daily (provider, location, forecast_time)'
    ELSE 'ALTER TABLE forecast_daily ADD UNIQUE KEY uq_forecast_daily (provider, location, forecast_time)'
END;
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
