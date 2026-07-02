-- Migration: 20260702_add_caqi.sql
-- Add EU CAQI (CITEAIR) columns alongside the existing US EPA AQI columns
-- for the Davis AirLink sensor. Computed from current (hourly-equivalent)
-- PM concentration rather than NowCast — CAQI is a real-time hourly index,
-- unlike the US AQI's 12h-smoothed NowCast convention. Columns are NULL for
-- all non-AirLink stations, same as the existing aqi_pm2p5/aqi_pm10.

USE weatherdatalogger;

ALTER TABLE realtime
    ADD COLUMN IF NOT EXISTS caqi_pm2p5 SMALLINT UNSIGNED NULL COMMENT 'EU CAQI (CITEAIR) from current PM2.5' AFTER aqi_pm10,
    ADD COLUMN IF NOT EXISTS caqi_pm10  SMALLINT UNSIGNED NULL COMMENT 'EU CAQI (CITEAIR) from current PM10'  AFTER caqi_pm2p5;

ALTER TABLE history
    ADD COLUMN IF NOT EXISTS caqi_pm2p5 SMALLINT UNSIGNED NULL AFTER aqi_pm10,
    ADD COLUMN IF NOT EXISTS caqi_pm10  SMALLINT UNSIGNED NULL AFTER caqi_pm2p5;

ALTER TABLE history_charting
    ADD COLUMN IF NOT EXISTS caqi_pm2p5 SMALLINT UNSIGNED NULL AFTER aqi_pm10,
    ADD COLUMN IF NOT EXISTS caqi_pm10  SMALLINT UNSIGNED NULL AFTER caqi_pm2p5;

-- ─────────────────────────────────────────────────────────────────────────────
-- View: combined_realtime — add the two new AirLink columns
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW combined_realtime AS
SELECT
    -- Timestamps
    d.recorded_at                   AS recorded_at,
    t.recorded_at                   AS tempest_recorded_at,
    a.recorded_at                   AS airlink_recorded_at,
    -- Wind (Davis)
    d.wind_lull_ms,
    d.wind_avg_ms,
    d.wind_gust_ms,
    d.wind_direction_deg,
    -- Pressure (Tempest — Davis ISS has no barometer)
    t.station_pressure_mb,
    t.sea_level_pressure_mb,
    t.pressure_trend_mb,
    t.pressure_trend,
    t.sea_level_pressure_trend_mb,
    t.sea_level_pressure_trend,
    -- Temperature & humidity (Davis)
    d.air_temperature_c,
    d.relative_humidity_pct,
    d.dew_point_c,
    t.wet_bulb_c,
    t.delta_t_c,
    d.feels_like_c,
    d.heat_index_c,
    d.wind_chill_c,
    -- Solar & UV (Tempest — no sensor fitted on the Davis ISS)
    t.illuminance_lux,
    t.uv_index,
    t.solar_radiation_wm2,
    -- Rain (Davis)
    d.rain_accumulation_mm,
    d.rain_rate_mmh,
    -- Lightning (Tempest — Davis has no lightning detector)
    t.lightning_last_detected,
    t.lightning_count_3h,
    t.lightning_min_dist_3h_km,
    t.lightning_max_dist_3h_km,
    -- Air properties
    d.vapor_pressure_mb,
    t.air_density_kgm3,
    -- Device
    t.battery_volts,
    d.battery_low                   AS davis_battery_low,
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
    a.aqi_pm10,
    a.caqi_pm2p5,
    a.caqi_pm10
FROM
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = 'davis'
        LIMIT  1
    ) d
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = 'tempest'
        LIMIT  1
    ) t ON TRUE
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = 'airlink'
        LIMIT  1
    ) a ON TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- Event: evt_aggregate_history_charting — add the two new AirLink columns
-- ─────────────────────────────────────────────────────────────────────────────
DROP EVENT IF EXISTS evt_aggregate_history_charting;

CREATE EVENT evt_aggregate_history_charting
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
        davis_battery_low,
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
        aqi_pm10,
        caqi_pm2p5,
        caqi_pm10
    )
    SELECT
        window_start,
        -- Wind (Davis)
        MIN(CASE WHEN station_type = 'davis' THEN wind_lull_ms END),
        AVG(CASE WHEN station_type = 'davis' THEN wind_avg_ms END),
        MAX(CASE WHEN station_type = 'davis' THEN wind_gust_ms END),
        MOD(ROUND(DEGREES(ATAN2(
            AVG(CASE WHEN station_type = 'davis' THEN SIN(RADIANS(wind_direction_deg)) END),
            AVG(CASE WHEN station_type = 'davis' THEN COS(RADIANS(wind_direction_deg)) END)
        ))) + 360, 360),
        -- Pressure (Tempest)
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
        -- Temperature & humidity (Davis, except wet bulb / delta T)
        AVG(CASE WHEN station_type = 'davis' THEN air_temperature_c END),
        AVG(CASE WHEN station_type = 'davis' THEN relative_humidity_pct END),
        AVG(CASE WHEN station_type = 'davis' THEN dew_point_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN wet_bulb_c END),
        AVG(CASE WHEN station_type = 'tempest' THEN delta_t_c END),
        AVG(CASE WHEN station_type = 'davis' THEN feels_like_c END),
        AVG(CASE WHEN station_type = 'davis' THEN heat_index_c END),
        AVG(CASE WHEN station_type = 'davis' THEN wind_chill_c END),
        -- Solar & UV (Tempest)
        ROUND(AVG(CASE WHEN station_type = 'tempest' THEN illuminance_lux END)),
        AVG(CASE WHEN station_type = 'tempest' THEN uv_index END),
        AVG(CASE WHEN station_type = 'tempest' THEN solar_radiation_wm2 END),
        -- Rain (Davis)
        SUM(CASE WHEN station_type = 'davis' THEN rain_accumulation_mm END),
        MAX(CASE WHEN station_type = 'davis' THEN rain_rate_mmh END),
        -- Lightning (Tempest)
        MAX(CASE WHEN station_type = 'tempest' THEN lightning_last_detected END),
        MAX(CASE WHEN station_type = 'tempest' THEN lightning_count_3h END),
        MIN(CASE WHEN station_type = 'tempest' THEN lightning_min_dist_3h_km END),
        MAX(CASE WHEN station_type = 'tempest' THEN lightning_max_dist_3h_km END),
        -- Air properties
        AVG(CASE WHEN station_type = 'davis' THEN vapor_pressure_mb END),
        AVG(CASE WHEN station_type = 'tempest' THEN air_density_kgm3 END),
        -- Device
        AVG(CASE WHEN station_type = 'tempest' THEN battery_volts END),
        MAX(CASE WHEN station_type = 'davis' THEN battery_low END),
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
        MAX(CASE WHEN station_type = 'airlink' THEN aqi_pm10 END),
        MAX(CASE WHEN station_type = 'airlink' THEN caqi_pm2p5 END),
        MAX(CASE WHEN station_type = 'airlink' THEN caqi_pm10 END)
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
          AND s.station_type IN ('tempest', 'airlink', 'davis')
    ) windowed
    GROUP BY window_start;
