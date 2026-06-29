-- Run once after 01_create_database.sql:
--   mysql -u weatherlogger -p weatherdatalogger < /path/to/database/02_create_tables.sql

USE weatherdatalogger;

-- Tracks which migration scripts have been applied so the deploy script can
-- skip files that were already run on a previous deploy.
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   VARCHAR(255) NOT NULL,
    applied_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (filename)
) ENGINE=InnoDB;

-- One row per physical station device. station_id matches the serial number
-- broadcast by the hardware (e.g. "ST-00000512" for a Tempest sensor).
CREATE TABLE IF NOT EXISTS stations (
    id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    station_id   VARCHAR(32)   NOT NULL,
    station_type VARCHAR(32)   NOT NULL COMMENT 'tempest | davis',
    name         VARCHAR(128)  NULL,
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_stations_station_id (station_id)
) ENGINE=InnoDB;

-- Latest observation per station — one row per station_id, replaced on every
-- incoming MQTT message (~every 10-15 s). Use INSERT … ON DUPLICATE KEY UPDATE.
CREATE TABLE IF NOT EXISTS realtime (
    station_id                  VARCHAR(32)   NOT NULL,
    recorded_at                 DATETIME      NOT NULL,
    -- wind
    wind_lull_ms                FLOAT         NULL,
    wind_avg_ms                 FLOAT         NULL,
    wind_gust_ms                FLOAT         NULL,
    wind_direction_deg          SMALLINT UNSIGNED NULL,
    -- pressure
    station_pressure_mb         FLOAT         NULL,
    sea_level_pressure_mb       FLOAT         NULL,
    pressure_trend_mb           FLOAT         NULL,
    pressure_trend              VARCHAR(16)   NULL COMMENT 'Rising | Steady | Falling',
    sea_level_pressure_trend_mb FLOAT         NULL,
    sea_level_pressure_trend    VARCHAR(16)   NULL COMMENT 'Rising | Steady | Falling',
    -- temperature & humidity
    air_temperature_c           FLOAT         NULL,
    relative_humidity_pct       FLOAT         NULL,
    dew_point_c                 FLOAT         NULL,
    wet_bulb_c                  FLOAT         NULL,
    delta_t_c                   FLOAT         NULL,
    feels_like_c                FLOAT         NULL,
    heat_index_c                FLOAT         NULL,
    wind_chill_c                FLOAT         NULL,
    -- solar & UV
    illuminance_lux             INT UNSIGNED  NULL,
    uv_index                    FLOAT         NULL,
    solar_radiation_wm2         FLOAT         NULL,
    -- rain
    rain_accumulation_mm        FLOAT         NULL,
    rain_rate_mmh               FLOAT         NULL,
    -- lightning
    lightning_last_detected     DATETIME      NULL,
    lightning_count_3h          SMALLINT UNSIGNED NULL,
    lightning_min_dist_3h_km    FLOAT         NULL,
    lightning_max_dist_3h_km    FLOAT         NULL,
    -- air properties
    vapor_pressure_mb           FLOAT         NULL,
    air_density_kgm3            FLOAT         NULL,
    -- device
    battery_volts               FLOAT         NULL,
    PRIMARY KEY (station_id),
    CONSTRAINT fk_realtime_station
        FOREIGN KEY (station_id) REFERENCES stations (station_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

-- Full observation history — every reading appended, never updated. Used for
-- charting and trend analysis. Partition by month if row count grows very large.
CREATE TABLE IF NOT EXISTS history (
    id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    station_id                  VARCHAR(32)   NOT NULL,
    recorded_at                 DATETIME      NOT NULL,
    -- wind
    wind_lull_ms                FLOAT         NULL,
    wind_avg_ms                 FLOAT         NULL,
    wind_gust_ms                FLOAT         NULL,
    wind_direction_deg          SMALLINT UNSIGNED NULL,
    -- pressure
    station_pressure_mb         FLOAT         NULL,
    sea_level_pressure_mb       FLOAT         NULL,
    pressure_trend_mb           FLOAT         NULL,
    pressure_trend              VARCHAR(16)   NULL,
    sea_level_pressure_trend_mb FLOAT         NULL,
    sea_level_pressure_trend    VARCHAR(16)   NULL,
    -- temperature & humidity
    air_temperature_c           FLOAT         NULL,
    relative_humidity_pct       FLOAT         NULL,
    dew_point_c                 FLOAT         NULL,
    wet_bulb_c                  FLOAT         NULL,
    delta_t_c                   FLOAT         NULL,
    feels_like_c                FLOAT         NULL,
    heat_index_c                FLOAT         NULL,
    wind_chill_c                FLOAT         NULL,
    -- solar & UV
    illuminance_lux             INT UNSIGNED  NULL,
    uv_index                    FLOAT         NULL,
    solar_radiation_wm2         FLOAT         NULL,
    -- rain
    rain_accumulation_mm        FLOAT         NULL,
    rain_rate_mmh               FLOAT         NULL,
    -- lightning
    lightning_last_detected     DATETIME      NULL,
    lightning_count_3h          SMALLINT UNSIGNED NULL,
    lightning_min_dist_3h_km    FLOAT         NULL,
    lightning_max_dist_3h_km    FLOAT         NULL,
    -- air properties
    vapor_pressure_mb           FLOAT         NULL,
    air_density_kgm3            FLOAT         NULL,
    -- device
    battery_volts               FLOAT         NULL,
    PRIMARY KEY (id),
    KEY idx_history_station_time (station_id, recorded_at),
    CONSTRAINT fk_history_station
        FOREIGN KEY (station_id) REFERENCES stations (station_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;
