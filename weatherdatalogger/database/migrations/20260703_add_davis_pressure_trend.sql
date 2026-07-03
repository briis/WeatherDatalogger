-- Migration: 20260703_add_davis_pressure_trend.sql
-- The Davis receiver's BME280 now computes its own sea-level pressure and
-- 3-hour trend on-device (see davis-vantage-receiver.yaml), not just the
-- raw station pressure added in migrations/20260703_add_davis_indoor_sensors.sql.
--
-- sea_level_pressure_mb/pressure_trend_mb/pressure_trend/
-- sea_level_pressure_trend_mb/sea_level_pressure_trend already exist on
-- realtime/history (shared with Tempest's `pressure` role) — no new column
-- needed there, it's just populated now for davis rows too. Only
-- history_charting needs new davis_-prefixed columns, since it already
-- has separate station_pressure_mb vs. davis_station_pressure_mb columns
-- from the previous migration and these follow the same pattern.

USE weatherdatalogger;

ALTER TABLE history_charting
    ADD COLUMN IF NOT EXISTS davis_sea_level_pressure_mb       FLOAT       NULL AFTER davis_station_pressure_mb,
    ADD COLUMN IF NOT EXISTS davis_pressure_trend_mb           FLOAT       NULL AFTER davis_sea_level_pressure_mb,
    ADD COLUMN IF NOT EXISTS davis_pressure_trend              VARCHAR(16) NULL AFTER davis_pressure_trend_mb,
    ADD COLUMN IF NOT EXISTS davis_sea_level_pressure_trend_mb FLOAT       NULL AFTER davis_pressure_trend,
    ADD COLUMN IF NOT EXISTS davis_sea_level_pressure_trend    VARCHAR(16) NULL AFTER davis_sea_level_pressure_trend_mb;

-- ─────────────────────────────────────────────────────────────────────────────
-- View: combined_realtime — adds the 5 davis_-prefixed sea-level/trend
-- columns, sourced from the existing temp_humidity(davis) join (th).
-- Otherwise identical to migrations/20260703_add_davis_indoor_sensors.sql.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW combined_realtime AS
SELECT
    -- Timestamps
    w.recorded_at                   AS recorded_at,
    pr.recorded_at                  AS tempest_recorded_at,
    aq.recorded_at                  AS airlink_recorded_at,
    -- Wind
    w.wind_lull_ms,
    w.wind_avg_ms,
    w.wind_gust_ms,
    w.wind_direction_deg,
    -- Pressure (+ wet bulb/delta T/air density/battery — bundled, see station_roles)
    pr.station_pressure_mb,
    pr.sea_level_pressure_mb,
    pr.pressure_trend_mb,
    pr.pressure_trend,
    pr.sea_level_pressure_trend_mb,
    pr.sea_level_pressure_trend,
    -- Temperature & humidity
    th.air_temperature_c,
    th.relative_humidity_pct,
    th.dew_point_c,
    pr.wet_bulb_c,
    pr.delta_t_c,
    th.feels_like_c,
    th.heat_index_c,
    th.wind_chill_c,
    -- Solar & UV
    su.illuminance_lux,
    su.uv_index,
    su.solar_radiation_wm2,
    -- Rain
    rn.rain_accumulation_mm,
    rn.rain_rate_mmh,
    -- Lightning
    lt.lightning_last_detected,
    lt.lightning_count_3h,
    lt.lightning_min_dist_3h_km,
    lt.lightning_max_dist_3h_km,
    -- Air properties
    th.vapor_pressure_mb,
    pr.air_density_kgm3,
    -- Device
    pr.battery_volts,
    th.battery_low                  AS davis_battery_low,
    -- Indoor (Davis receiver's own BME280 — co-located with the receiver,
    -- not the outdoor ISS; sourced from the same temp_humidity(davis) join
    -- as davis_battery_low above, since it's the same MQTT observation row).
    -- The receiver computes its own sea-level pressure + 3h trend on-device
    -- (see davis-vantage-receiver.yaml), independently of pr.* above (the
    -- `pressure` role, e.g. Tempest) — the two are not merged, both remain
    -- available side by side.
    th.indoor_temperature_c,
    th.indoor_humidity_pct,
    th.station_pressure_mb          AS davis_station_pressure_mb,
    th.sea_level_pressure_mb        AS davis_sea_level_pressure_mb,
    th.pressure_trend_mb            AS davis_pressure_trend_mb,
    th.pressure_trend               AS davis_pressure_trend,
    th.sea_level_pressure_trend_mb  AS davis_sea_level_pressure_trend_mb,
    th.sea_level_pressure_trend     AS davis_sea_level_pressure_trend,
    -- Air quality — PM1/PM2.5/PM10/AQI/CAQI
    aq.pm_1_ugm3,
    aq.pm_2p5_ugm3,
    aq.pm_2p5_1h_ugm3,
    aq.pm_2p5_3h_ugm3,
    aq.pm_2p5_24h_ugm3,
    aq.pm_2p5_nowcast_ugm3,
    aq.pm_10_ugm3,
    aq.pm_10_1h_ugm3,
    aq.pm_10_3h_ugm3,
    aq.pm_10_24h_ugm3,
    aq.pm_10_nowcast_ugm3,
    aq.aqi_pm2p5,
    aq.aqi_pm10,
    aq.caqi_pm2p5,
    aq.caqi_pm10
FROM
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'wind')
        LIMIT  1
    ) w
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'pressure')
        LIMIT  1
    ) pr ON TRUE
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'temp_humidity')
        LIMIT  1
    ) th ON TRUE
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'solar_uv')
        LIMIT  1
    ) su ON TRUE
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'rain')
        LIMIT  1
    ) rn ON TRUE
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'lightning')
        LIMIT  1
    ) lt ON TRUE
LEFT JOIN
    (
        SELECT r.*
        FROM   realtime r
        JOIN   stations s ON r.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'air_quality')
        LIMIT  1
    ) aq ON TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- Event: evt_aggregate_history_charting — adds the same 5 davis_-prefixed
-- columns, aggregated from the temp_humidity(davis) role.
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
        indoor_temperature_c,
        indoor_humidity_pct,
        davis_station_pressure_mb,
        davis_sea_level_pressure_mb,
        davis_pressure_trend_mb,
        davis_pressure_trend,
        davis_sea_level_pressure_trend_mb,
        davis_sea_level_pressure_trend,
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
        -- Wind
        MIN(CASE WHEN station_type = roles.wind_type THEN wind_lull_ms END),
        AVG(CASE WHEN station_type = roles.wind_type THEN wind_avg_ms END),
        MAX(CASE WHEN station_type = roles.wind_type THEN wind_gust_ms END),
        MOD(ROUND(DEGREES(ATAN2(
            AVG(CASE WHEN station_type = roles.wind_type THEN SIN(RADIANS(wind_direction_deg)) END),
            AVG(CASE WHEN station_type = roles.wind_type THEN COS(RADIANS(wind_direction_deg)) END)
        ))) + 360, 360),
        -- Pressure (+ wet bulb/delta T/air density/battery — bundled)
        AVG(CASE WHEN station_type = roles.pressure_type THEN station_pressure_mb END),
        AVG(CASE WHEN station_type = roles.pressure_type THEN sea_level_pressure_mb END),
        AVG(CASE WHEN station_type = roles.pressure_type THEN pressure_trend_mb END),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = roles.pressure_type THEN pressure_trend END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
        AVG(CASE WHEN station_type = roles.pressure_type THEN sea_level_pressure_trend_mb END),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = roles.pressure_type THEN sea_level_pressure_trend END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
        -- Temperature & humidity
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN air_temperature_c END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN relative_humidity_pct END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN dew_point_c END),
        AVG(CASE WHEN station_type = roles.pressure_type THEN wet_bulb_c END),
        AVG(CASE WHEN station_type = roles.pressure_type THEN delta_t_c END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN feels_like_c END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN heat_index_c END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN wind_chill_c END),
        -- Solar & UV
        ROUND(AVG(CASE WHEN station_type = roles.solar_uv_type THEN illuminance_lux END)),
        AVG(CASE WHEN station_type = roles.solar_uv_type THEN uv_index END),
        AVG(CASE WHEN station_type = roles.solar_uv_type THEN solar_radiation_wm2 END),
        -- Rain — MAX, not SUM: rain_accumulation_mm is a cumulative
        -- "so far today" counter (resets at local midnight), not a
        -- per-observation delta, so the max value in the window is the
        -- running total as of the window's end
        MAX(CASE WHEN station_type = roles.rain_type THEN rain_accumulation_mm END),
        MAX(CASE WHEN station_type = roles.rain_type THEN rain_rate_mmh END),
        -- Lightning
        MAX(CASE WHEN station_type = roles.lightning_type THEN lightning_last_detected END),
        MAX(CASE WHEN station_type = roles.lightning_type THEN lightning_count_3h END),
        MIN(CASE WHEN station_type = roles.lightning_type THEN lightning_min_dist_3h_km END),
        MAX(CASE WHEN station_type = roles.lightning_type THEN lightning_max_dist_3h_km END),
        -- Air properties
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN vapor_pressure_mb END),
        AVG(CASE WHEN station_type = roles.pressure_type THEN air_density_kgm3 END),
        -- Device
        AVG(CASE WHEN station_type = roles.pressure_type THEN battery_volts END),
        MAX(CASE WHEN station_type = roles.temp_humidity_type THEN battery_low END),
        -- Indoor (Davis receiver's own BME280) — trend text = last value in
        -- window, same convention as the `pressure` role trend above
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN indoor_temperature_c END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN indoor_humidity_pct END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN station_pressure_mb END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN sea_level_pressure_mb END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN pressure_trend_mb END),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = roles.temp_humidity_type THEN pressure_trend END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN sea_level_pressure_trend_mb END),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = roles.temp_humidity_type THEN sea_level_pressure_trend END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
        -- Air quality
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_1_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_2p5_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_2p5_1h_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_2p5_3h_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_2p5_24h_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_2p5_nowcast_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_10_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_10_1h_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_10_3h_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_10_24h_ugm3 END),
        AVG(CASE WHEN station_type = roles.air_quality_type THEN pm_10_nowcast_ugm3 END),
        MAX(CASE WHEN station_type = roles.air_quality_type THEN aqi_pm2p5 END),
        MAX(CASE WHEN station_type = roles.air_quality_type THEN aqi_pm10 END),
        MAX(CASE WHEN station_type = roles.air_quality_type THEN caqi_pm2p5 END),
        MAX(CASE WHEN station_type = roles.air_quality_type THEN caqi_pm10 END)
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
          AND s.station_type IN (SELECT DISTINCT station_type FROM station_roles)
    ) windowed
    CROSS JOIN (
        SELECT
            MAX(CASE WHEN role = 'wind'          THEN station_type END) AS wind_type,
            MAX(CASE WHEN role = 'pressure'      THEN station_type END) AS pressure_type,
            MAX(CASE WHEN role = 'temp_humidity' THEN station_type END) AS temp_humidity_type,
            MAX(CASE WHEN role = 'solar_uv'      THEN station_type END) AS solar_uv_type,
            MAX(CASE WHEN role = 'rain'          THEN station_type END) AS rain_type,
            MAX(CASE WHEN role = 'lightning'     THEN station_type END) AS lightning_type,
            MAX(CASE WHEN role = 'air_quality'   THEN station_type END) AS air_quality_type
        FROM station_roles
    ) roles
    GROUP BY window_start;
