-- Migration: 20260630_add_history_charting.sql
-- Pre-aggregated 10-minute summary table for charting.
--
-- One combined row per 10-minute window (clock-aligned: 00:00, 00:10, …).
-- Merges Tempest (weather) and AirLink (air quality) into a single row,
-- matching the pattern of the combined_realtime view.
--
-- Populated by the evt_aggregate_history_charting MariaDB event.
-- The event must be enabled once on the server (requires SUPER or
-- SYSTEM_VARIABLES_ADMIN):
--
--   SET GLOBAL event_scheduler = ON;
--
-- Or add the following to [mysqld] in /etc/mysql/my.cnf (persistent):
--   event_scheduler = ON

USE weatherdatalogger;

-- ─────────────────────────────────────────────────────────────────────────────
-- Table
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

    -- Lightning (Tempest) — last detected=MAX, count=MAX (rolling 3h from device),
    --                        min dist=MIN, max dist=MAX
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
-- Event
-- ─────────────────────────────────────────────────────────────────────────────
-- Runs every 10 minutes. Aggregates the completed window(s) within the last
-- 30 minutes so late-arriving MQTT messages are included.
-- INSERT IGNORE makes re-runs safe: already-written windows are skipped.
--
-- Wind direction uses a vector (circular) average via ATAN2 so readings near
-- 0°/360° (e.g. 350° and 10°) correctly average to 0° rather than 180°.
--
-- Pressure-trend text fields (e.g. 'Rising', 'Steady', 'Falling') use
-- GROUP_CONCAT ordered DESC so SUBSTRING_INDEX picks the most-recent value.
-- GROUP_CONCAT skips NULLs, so AirLink rows never pollute Tempest fields.
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
            FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(h.recorded_at) / 600) * 600) AS window_start
        FROM  history  h
        JOIN  stations s ON h.station_id = s.station_id
        WHERE h.recorded_at >= FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(NOW()) / 600) * 600) - INTERVAL 30 MINUTE
          AND h.recorded_at <  FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(NOW()) / 600) * 600)
          AND s.station_type IN ('tempest', 'airlink')
    ) windowed
    GROUP BY window_start;
