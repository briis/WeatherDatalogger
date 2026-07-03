-- Migration: 20260703_add_station_roles.sql
-- Make combined_realtime / history_charting sourceable from any installed
-- station type, instead of hardcoding davis/tempest/airlink. Each functional
-- "role" (wind, pressure, ...) is mapped to a station_type in the new
-- station_roles table; the view/event look up that mapping at query time
-- instead of hardcoding a literal station_type. Seeded to match today's
-- behavior exactly, so this migration is a no-op until a row is changed.
--
-- To reassign a role (e.g. no Davis, wind measured by a Tempest instead):
--   UPDATE station_roles SET station_type = 'tempest' WHERE role = 'wind';
--
-- Role -> columns:
--   wind          wind_lull_ms, wind_avg_ms, wind_gust_ms, wind_direction_deg
--   temp_humidity air_temperature_c, relative_humidity_pct, dew_point_c,
--                 feels_like_c, heat_index_c, wind_chill_c, vapor_pressure_mb,
--                 battery_low (-> davis_battery_low)
--   rain          rain_accumulation_mm, rain_rate_mmh
--   pressure      station/sea_level_pressure_mb + trends, wet_bulb_c,
--                 delta_t_c, air_density_kgm3, battery_volts — bundled
--                 together since they've only ever come from one station
--                 type (Tempest) at a time; not meaningfully splittable
--   solar_uv      illuminance_lux, uv_index, solar_radiation_wm2
--   lightning     lightning_last_detected/count_3h/min_dist_3h_km/max_dist_3h_km
--   air_quality   pm_*, aqi_*, caqi_*
--
-- Known limitation: `wind` is the mandatory anchor (INNER JOIN) in
-- combined_realtime, same as `davis` is today — a setup with no station
-- that reports wind (e.g. AirLink-only) will still get zero rows back,
-- regardless of what `wind` is set to.

USE weatherdatalogger;

CREATE TABLE IF NOT EXISTS station_roles (
    role         VARCHAR(32) NOT NULL COMMENT 'wind | temp_humidity | rain | pressure | solar_uv | lightning | air_quality',
    station_type VARCHAR(32) NOT NULL COMMENT 'tempest | airlink | davis | ... — must match stations.station_type',
    PRIMARY KEY (role)
) ENGINE=InnoDB;

INSERT IGNORE INTO station_roles (role, station_type) VALUES
    ('wind',          'davis'),
    ('temp_humidity', 'davis'),
    ('rain',          'davis'),
    ('pressure',      'tempest'),
    ('solar_uv',      'tempest'),
    ('lightning',     'tempest'),
    ('air_quality',   'airlink');

-- ─────────────────────────────────────────────────────────────────────────────
-- View: combined_realtime — role-based sourcing instead of hardcoded
-- station_type literals. Column names are historical and no longer strictly
-- literal: "tempest_recorded_at" reflects the `pressure` role, not literally
-- a Tempest station once reassigned; kept as-is to avoid breaking existing
-- dashboards built against this view.
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
-- Event: evt_aggregate_history_charting — same role-based sourcing. The
-- role -> station_type mapping is resolved once per run via a CROSS JOIN
-- against a single pivoted row (roles), rather than repeating a scalar
-- subquery in every CASE WHEN.
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
        -- Rain
        SUM(CASE WHEN station_type = roles.rain_type THEN rain_accumulation_mm END),
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
