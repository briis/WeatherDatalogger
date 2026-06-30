-- Migration: 20260701_fix_charting_event_timezone.sql
-- Fix evt_aggregate_history_charting to use UTC_TIMESTAMP() instead of NOW().
--
-- recorded_at is stored in UTC (db_writer uses datetime.fromtimestamp(..., tz=UTC)).
-- The original event used NOW() and FROM_UNIXTIME/UNIX_TIMESTAMP, which both
-- return/interpret values in the server's local timezone (e.g. CEST = UTC+2),
-- causing the window boundaries to be 2 hours ahead of the stored data.
-- Result: the WHERE clause found zero rows and nothing was inserted.
--
-- Fix: pure UTC_TIMESTAMP() arithmetic with no FROM_UNIXTIME conversion.

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
