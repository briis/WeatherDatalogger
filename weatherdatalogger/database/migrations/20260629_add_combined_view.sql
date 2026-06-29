-- Migration: 20260629_add_combined_view.sql
-- Create a combined_realtime view that merges the latest reading from each
-- station type into a single row.  Weather fields come from 'tempest',
-- air quality fields come from 'airlink'.
--
-- Uses LEFT JOIN so the view returns a row as long as a Tempest station is
-- registered, with air quality columns NULL until an AirLink is present.

USE weatherdatalogger;

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
