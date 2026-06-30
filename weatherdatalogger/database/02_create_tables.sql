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
    station_type VARCHAR(32)   NOT NULL COMMENT 'tempest | airlink | davis',
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
    -- air quality — Davis AirLink (NULL for other station types)
    pm_1_ugm3                   FLOAT         NULL COMMENT 'PM1.0 2-min avg µg/m³',
    pm_2p5_ugm3                 FLOAT         NULL COMMENT 'PM2.5 2-min avg µg/m³',
    pm_2p5_1h_ugm3              FLOAT         NULL COMMENT 'PM2.5 1-hour avg µg/m³',
    pm_2p5_3h_ugm3              FLOAT         NULL COMMENT 'PM2.5 3-hour avg µg/m³',
    pm_2p5_24h_ugm3             FLOAT         NULL COMMENT 'PM2.5 24-hour avg µg/m³',
    pm_2p5_nowcast_ugm3         FLOAT         NULL COMMENT 'PM2.5 NowCast µg/m³',
    pm_10_ugm3                  FLOAT         NULL COMMENT 'PM10 2-min avg µg/m³',
    pm_10_1h_ugm3               FLOAT         NULL COMMENT 'PM10 1-hour avg µg/m³',
    pm_10_3h_ugm3               FLOAT         NULL COMMENT 'PM10 3-hour avg µg/m³',
    pm_10_24h_ugm3              FLOAT         NULL COMMENT 'PM10 24-hour avg µg/m³',
    pm_10_nowcast_ugm3          FLOAT         NULL COMMENT 'PM10 NowCast µg/m³',
    aqi_pm2p5                   SMALLINT UNSIGNED NULL COMMENT 'US EPA AQI from PM2.5 NowCast',
    aqi_pm10                    SMALLINT UNSIGNED NULL COMMENT 'US EPA AQI from PM10 NowCast',
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
    -- air quality — Davis AirLink (NULL for other station types)
    pm_1_ugm3                   FLOAT         NULL,
    pm_2p5_ugm3                 FLOAT         NULL,
    pm_2p5_1h_ugm3              FLOAT         NULL,
    pm_2p5_3h_ugm3              FLOAT         NULL,
    pm_2p5_24h_ugm3             FLOAT         NULL,
    pm_2p5_nowcast_ugm3         FLOAT         NULL,
    pm_10_ugm3                  FLOAT         NULL,
    pm_10_1h_ugm3               FLOAT         NULL,
    pm_10_3h_ugm3               FLOAT         NULL,
    pm_10_24h_ugm3              FLOAT         NULL,
    pm_10_nowcast_ugm3          FLOAT         NULL,
    aqi_pm2p5                   SMALLINT UNSIGNED NULL,
    aqi_pm10                    SMALLINT UNSIGNED NULL,
    PRIMARY KEY (id),
    KEY idx_history_station_time (station_id, recorded_at),
    CONSTRAINT fk_history_station
        FOREIGN KEY (station_id) REFERENCES stations (station_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─────────────────────────────────────────────────────────────────────────────
-- View: combined_realtime
-- Merges the latest Tempest (weather) and AirLink (air quality) readings into
-- a single row. Uses LEFT JOIN so the view returns a row as long as a Tempest
-- station is registered, with air quality columns NULL until an AirLink is present.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW combined_realtime AS
SELECT
    -- Timestamps
    t.recorded_at                   AS recorded_at,
    a.recorded_at                   AS airlink_recorded_at,
    -- Wind (Tempest)
    t.wind_lull_ms,
    t.wind_avg_ms,
    t.wind_gust_ms,
    t.wind_direction_deg,
    -- Pressure (Tempest)
    t.station_pressure_mb,
    t.sea_level_pressure_mb,
    t.pressure_trend_mb,
    t.pressure_trend,
    t.sea_level_pressure_trend_mb,
    t.sea_level_pressure_trend,
    -- Temperature & humidity (Tempest)
    t.air_temperature_c,
    t.relative_humidity_pct,
    t.dew_point_c,
    t.wet_bulb_c,
    t.delta_t_c,
    t.feels_like_c,
    t.heat_index_c,
    t.wind_chill_c,
    -- Solar & UV (Tempest)
    t.illuminance_lux,
    t.uv_index,
    t.solar_radiation_wm2,
    -- Rain (Tempest)
    t.rain_accumulation_mm,
    t.rain_rate_mmh,
    -- Lightning (Tempest)
    t.lightning_last_detected,
    t.lightning_count_3h,
    t.lightning_min_dist_3h_km,
    t.lightning_max_dist_3h_km,
    -- Air properties (Tempest)
    t.vapor_pressure_mb,
    t.air_density_kgm3,
    -- Device (Tempest)
    t.battery_volts,
    -- Air quality — PM1/PM2.5/PM10 (AirLink)
    a.pm_1_ugm3,
    a.pm_2p5_ugm3,
    a.pm_2p5_1h_ugm3,
    a.pm_2p5_3h_ugm3,
    a.pm_2p5_24h_ugm3,
    a.pm_2p5_nowcast_ugm3,
    a.pm_10_ugm3,
    a.pm_10_1h_ugm3,
    a.pm_10_3h_ugm3,
    a.pm_10_24h_ugm3,
    a.pm_10_nowcast_ugm3,
    a.aqi_pm2p5,
    a.aqi_pm10
FROM
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = 'tempest'
        LIMIT  1
    ) t
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = 'airlink'
        LIMIT  1
    ) a ON TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- Table: history_charting
-- Pre-aggregated 10-minute windows combining all station types.
-- One combined row per window_start (clock-aligned UTC: 00:00, 00:10, …).
-- Populated by the evt_aggregate_history_charting event below.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS history_charting (
    id                          BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    window_start                DATETIME          NOT NULL COMMENT '10-min boundary UTC (floor)',

    -- Wind (Tempest) — lull=MIN, avg=AVG, gust=MAX, dir=circular AVG
    wind_lull_ms                FLOAT             NULL,
    wind_avg_ms                 FLOAT             NULL,
    wind_gust_ms                FLOAT             NULL,
    wind_direction_deg          SMALLINT UNSIGNED NULL,

    -- Pressure (Tempest) — AVG; trend text = last value in window
    station_pressure_mb         FLOAT             NULL,
    sea_level_pressure_mb       FLOAT             NULL,
    pressure_trend_mb           FLOAT             NULL,
    pressure_trend              VARCHAR(16)       NULL,
    sea_level_pressure_trend_mb FLOAT             NULL,
    sea_level_pressure_trend    VARCHAR(16)       NULL,

    -- Temperature & humidity (Tempest) — AVG
    air_temperature_c           FLOAT             NULL,
    relative_humidity_pct       FLOAT             NULL,
    dew_point_c                 FLOAT             NULL,
    wet_bulb_c                  FLOAT             NULL,
    delta_t_c                   FLOAT             NULL,
    feels_like_c                FLOAT             NULL,
    heat_index_c                FLOAT             NULL,
    wind_chill_c                FLOAT             NULL,

    -- Solar & UV (Tempest) — AVG
    illuminance_lux             INT UNSIGNED      NULL,
    uv_index                    FLOAT             NULL,
    solar_radiation_wm2         FLOAT             NULL,

    -- Rain (Tempest) — accumulation=SUM (per-minute delta), rate=MAX
    rain_accumulation_mm        FLOAT             NULL,
    rain_rate_mmh               FLOAT             NULL,

    -- Lightning (Tempest)
    lightning_last_detected     DATETIME          NULL,
    lightning_count_3h          SMALLINT UNSIGNED NULL,
    lightning_min_dist_3h_km    FLOAT             NULL,
    lightning_max_dist_3h_km    FLOAT             NULL,

    -- Air properties (Tempest) — AVG
    vapor_pressure_mb           FLOAT             NULL,
    air_density_kgm3            FLOAT             NULL,

    -- Device (Tempest) — AVG
    battery_volts               FLOAT             NULL,

    -- Air quality (AirLink) — instant PM=AVG, pre-averaged PM=AVG, AQI=MAX
    pm_1_ugm3                   FLOAT             NULL,
    pm_2p5_ugm3                 FLOAT             NULL,
    pm_2p5_1h_ugm3              FLOAT             NULL,
    pm_2p5_3h_ugm3              FLOAT             NULL,
    pm_2p5_24h_ugm3             FLOAT             NULL,
    pm_2p5_nowcast_ugm3         FLOAT             NULL,
    pm_10_ugm3                  FLOAT             NULL,
    pm_10_1h_ugm3               FLOAT             NULL,
    pm_10_3h_ugm3               FLOAT             NULL,
    pm_10_24h_ugm3              FLOAT             NULL,
    pm_10_nowcast_ugm3          FLOAT             NULL,
    aqi_pm2p5                   SMALLINT UNSIGNED NULL,
    aqi_pm10                    SMALLINT UNSIGNED NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_history_charting_window (window_start)
) ENGINE=InnoDB;

-- ─────────────────────────────────────────────────────────────────────────────
-- Event: evt_aggregate_history_charting
-- Runs every 10 minutes. Aggregates completed windows within the last 30
-- minutes so late-arriving MQTT messages are included.
-- INSERT IGNORE on the unique window_start key makes re-runs idempotent.
--
-- recorded_at is stored in UTC. UTC_TIMESTAMP() and pure datetime arithmetic
-- are used throughout to avoid mismatch when the server runs in a non-UTC
-- timezone. FROM_UNIXTIME/UNIX_TIMESTAMP are intentionally avoided.
--
-- Requires the event scheduler (enable once as MySQL root, or in my.cnf):
--   SET GLOBAL event_scheduler = ON;
-- ─────────────────────────────────────────────────────────────────────────────
CREATE EVENT IF NOT EXISTS evt_aggregate_history_charting
    ON SCHEDULE EVERY 10 MINUTE
    STARTS CURRENT_TIMESTAMP
DO
    INSERT IGNORE INTO history_charting (
        window_start,
        wind_lull_ms,
        wind_avg_ms,
        wind_gust_ms,
        wind_direction_deg,
        station_pressure_mb,
        sea_level_pressure_mb,
        pressure_trend_mb,
        pressure_trend,
        sea_level_pressure_trend_mb,
        sea_level_pressure_trend,
        air_temperature_c,
        relative_humidity_pct,
        dew_point_c,
        wet_bulb_c,
        delta_t_c,
        feels_like_c,
        heat_index_c,
        wind_chill_c,
        illuminance_lux,
        uv_index,
        solar_radiation_wm2,
        rain_accumulation_mm,
        rain_rate_mmh,
        lightning_last_detected,
        lightning_count_3h,
        lightning_min_dist_3h_km,
        lightning_max_dist_3h_km,
        vapor_pressure_mb,
        air_density_kgm3,
        battery_volts,
        pm_1_ugm3,
        pm_2p5_ugm3,
        pm_2p5_1h_ugm3,
        pm_2p5_3h_ugm3,
        pm_2p5_24h_ugm3,
        pm_2p5_nowcast_ugm3,
        pm_10_ugm3,
        pm_10_1h_ugm3,
        pm_10_3h_ugm3,
        pm_10_24h_ugm3,
        pm_10_nowcast_ugm3,
        aqi_pm2p5,
        aqi_pm10
    )
    SELECT
        window_start,
        -- Wind
        MIN(CASE WHEN station_type = 'tempest' THEN wind_lull_ms END),
        AVG(CASE WHEN station_type = 'tempest' THEN wind_avg_ms END),
        MAX(CASE WHEN station_type = 'tempest' THEN wind_gust_ms END),
        MOD(ROUND(DEGREES(ATAN2(
            AVG(CASE WHEN station_type = 'tempest' THEN SIN(RADIANS(wind_direction_deg)) END),
            AVG(CASE WHEN station_type = 'tempest' THEN COS(RADIANS(wind_direction_deg)) END)
        ))) + 360, 360),
        -- Pressure
        AVG(CASE WHEN station_type = 'tempest' THEN station_pressure_mb END),
        AVG(CASE WHEN station_type = 'tempest' THEN sea_level_pressure_mb END),
        AVG(CASE WHEN station_type = 'tempest' THEN pressure_trend_mb END),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = 'tempest' THEN pressure_trend END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
        AVG(CASE WHEN station_type = 'tempest' THEN sea_level_pressure_trend_mb END),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = 'tempest' THEN sea_level_pressure_trend END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
        -- Temperature & humidity
        AVG(CASE WHEN station_type = 'tempest' THEN air_temperature_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN relative_humidity_pct END),
        AVG(CASE WHEN station_type = 'tempest' THEN dew_point_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN wet_bulb_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN delta_t_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN feels_like_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN heat_index_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN wind_chill_c END),
        -- Solar & UV
        ROUND(AVG(CASE WHEN station_type = 'tempest' THEN illuminance_lux END)),
        AVG(CASE WHEN station_type = 'tempest' THEN uv_index END),
        AVG(CASE WHEN station_type = 'tempest' THEN solar_radiation_wm2 END),
        -- Rain
        SUM(CASE WHEN station_type = 'tempest' THEN rain_accumulation_mm END),
        MAX(CASE WHEN station_type = 'tempest' THEN rain_rate_mmh END),
        -- Lightning
        MAX(CASE WHEN station_type = 'tempest' THEN lightning_last_detected END),
        MAX(CASE WHEN station_type = 'tempest' THEN lightning_count_3h END),
        MIN(CASE WHEN station_type = 'tempest' THEN lightning_min_dist_3h_km END),
        MAX(CASE WHEN station_type = 'tempest' THEN lightning_max_dist_3h_km END),
        -- Air properties
        AVG(CASE WHEN station_type = 'tempest' THEN vapor_pressure_mb END),
        AVG(CASE WHEN station_type = 'tempest' THEN air_density_kgm3 END),
        -- Device
        AVG(CASE WHEN station_type = 'tempest' THEN battery_volts END),
        -- Air quality (AirLink)
        AVG(CASE WHEN station_type = 'airlink' THEN pm_1_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_2p5_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_2p5_1h_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_2p5_3h_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_2p5_24h_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_2p5_nowcast_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_10_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_10_1h_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_10_3h_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_10_24h_ugm3 END),
        AVG(CASE WHEN station_type = 'airlink' THEN pm_10_nowcast_ugm3 END),
        MAX(CASE WHEN station_type = 'airlink' THEN aqi_pm2p5 END),
        MAX(CASE WHEN station_type = 'airlink' THEN aqi_pm10 END)
    FROM (
        SELECT
            h.*,
            s.station_type,
            h.recorded_at
                - INTERVAL (MINUTE(h.recorded_at) % 10) MINUTE
                - INTERVAL SECOND(h.recorded_at) SECOND  AS window_start
        FROM  history  h
        JOIN  stations s ON h.station_id = s.station_id
        WHERE h.recorded_at >= (
                  UTC_TIMESTAMP()
                  - INTERVAL (MINUTE(UTC_TIMESTAMP()) % 10) MINUTE
                  - INTERVAL SECOND(UTC_TIMESTAMP()) SECOND
              ) - INTERVAL 30 MINUTE
          AND h.recorded_at <  (
                  UTC_TIMESTAMP()
                  - INTERVAL (MINUTE(UTC_TIMESTAMP()) % 10) MINUTE
                  - INTERVAL SECOND(UTC_TIMESTAMP()) SECOND
              )
          AND s.station_type IN ('tempest', 'airlink')
    ) windowed
    GROUP BY window_start;
