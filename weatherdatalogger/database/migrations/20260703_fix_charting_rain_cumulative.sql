-- Migration: 20260703_fix_charting_rain_cumulative.sql
-- Fix evt_aggregate_history_charting: rain_accumulation_mm was aggregated
-- with SUM, on the assumption (true back when Tempest supplied rain) that
-- each observation held a per-observation delta. Since Davis became the
-- rain-role source (migrations/20260702_davis_primary_combined_view.sql),
-- rain_accumulation_mm is actually a cumulative "rain so far today" counter,
-- republished unchanged on every packet and reset to 0 at local midnight
-- (see davis/README.md and davis-vantage-receiver.yaml). Summing it across a
-- 10-minute window summed the same running total repeatedly, inflating
-- every history_charting row for that column — same root cause as the
-- combined_realtime_stats rain_total_yesterday bug fixed alongside this.
--
-- Fix: MAX instead of SUM. The max value recorded in a window is that
-- window's most up-to-date running total, which is the correct value to
-- chart (a monotonically-increasing day-to-date line, resetting at each
-- local midnight) — not a per-window delta.
--
-- Known limitation: this only fixes the event going forward. Existing
-- history_charting rows with inflated rain_accumulation_mm, from when Davis
-- became the rain source up to now, are not backfilled by this migration.

USE weatherdatalogger;

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
