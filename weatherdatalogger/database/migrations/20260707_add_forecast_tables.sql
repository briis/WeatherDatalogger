-- Migration: 20260707_add_forecast_tables.sql
-- Adds forecast_current/forecast_hourly/forecast_daily, populated by
-- visualcrossing_datalogger.py (Visual Crossing Timeline Weather API) via
-- db_writer.py, which subscribes to
-- weatherdatalogger/forecast-<location>/{current,forecast_hourly,forecast_daily}.
--
-- All three hold only the latest fetch per `location` — not an append-only
-- history — since nothing currently needs to track how a forecast for a
-- given hour/day changed across successive fetches, just the current best
-- guess for driving a Home Assistant weather entity. `location` matches the
-- `location` config value in [visualcrossing] (defaults to "home"), not a
-- `stations` row — forecasts aren't tied to a physical device the way
-- `realtime`/`history` are.

USE weatherdatalogger;

-- One row per location, upserted on every fetch (like `realtime`).
CREATE TABLE IF NOT EXISTS forecast_current (
    location            VARCHAR(64)       NOT NULL,
    fetched_at          DATETIME          NOT NULL,
    condition           VARCHAR(32)       NULL COMMENT 'HA weather condition, e.g. partlycloudy',
    temperature_c       FLOAT             NULL,
    feels_like_c        FLOAT             NULL,
    humidity_pct        FLOAT             NULL,
    dew_point_c         FLOAT             NULL,
    wind_speed_ms       FLOAT             NULL,
    wind_gust_ms        FLOAT             NULL,
    wind_bearing_deg    SMALLINT UNSIGNED NULL,
    pressure_mb         FLOAT             NULL COMMENT 'Sea-level pressure',
    cloud_cover_pct     TINYINT UNSIGNED  NULL,
    uv_index            FLOAT             NULL,
    visibility_km       TINYINT UNSIGNED  NULL,
    solar_radiation_wm2 FLOAT             NULL,
    PRIMARY KEY (location)
) ENGINE=InnoDB;

-- One row per (location, forecast_time); each fetch replaces the full set
-- for that location (see db_writer.py) so hours that drop out of the
-- forecast window don't linger. No visibility_km/solar_radiation_wm2 —
-- Visual Crossing only reports those for current conditions, not forecasts.
CREATE TABLE IF NOT EXISTS forecast_hourly (
    id                             BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    location                       VARCHAR(64)       NOT NULL,
    forecast_time                  DATETIME          NOT NULL COMMENT 'UTC hour this row forecasts',
    fetched_at                     DATETIME          NOT NULL,
    condition                      VARCHAR(32)       NULL,
    temperature_c                  FLOAT             NULL,
    feels_like_c                   FLOAT             NULL,
    humidity_pct                   FLOAT             NULL,
    dew_point_c                    FLOAT             NULL,
    wind_speed_ms                  FLOAT             NULL,
    wind_gust_ms                   FLOAT             NULL,
    wind_bearing_deg               SMALLINT UNSIGNED NULL,
    pressure_mb                    FLOAT             NULL,
    cloud_cover_pct                TINYINT UNSIGNED  NULL,
    uv_index                       FLOAT             NULL,
    precipitation_mm               FLOAT             NULL,
    precipitation_probability_pct  TINYINT UNSIGNED  NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_forecast_hourly (location, forecast_time)
) ENGINE=InnoDB;

-- One row per (location, forecast_time); same replace-on-fetch approach as
-- forecast_hourly. temperature_high_c/temperature_low_c replace a single
-- temperature_c column since a daily forecast is a high/low pair, not one
-- instant reading.
CREATE TABLE IF NOT EXISTS forecast_daily (
    id                             BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    location                       VARCHAR(64)       NOT NULL,
    forecast_time                  DATETIME          NOT NULL COMMENT 'Day this row forecasts (as reported by the API — see Visual Crossing day datetime)',
    fetched_at                     DATETIME          NOT NULL,
    condition                      VARCHAR(32)       NULL,
    temperature_high_c             FLOAT             NULL,
    temperature_low_c              FLOAT             NULL,
    feels_like_c                   FLOAT             NULL,
    humidity_pct                   FLOAT             NULL,
    dew_point_c                    FLOAT             NULL,
    wind_speed_ms                  FLOAT             NULL,
    wind_gust_ms                   FLOAT             NULL,
    wind_bearing_deg               SMALLINT UNSIGNED NULL,
    pressure_mb                    FLOAT             NULL,
    cloud_cover_pct                TINYINT UNSIGNED  NULL,
    uv_index                       FLOAT             NULL,
    precipitation_mm               FLOAT             NULL,
    precipitation_probability_pct  TINYINT UNSIGNED  NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_forecast_daily (location, forecast_time)
) ENGINE=InnoDB;
