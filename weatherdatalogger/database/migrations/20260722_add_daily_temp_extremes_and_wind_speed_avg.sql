-- Migration: 20260722_add_daily_temp_extremes_and_wind_speed_avg.sql
-- Adds three more derived columns to combined_realtime_stats, needed for the
-- esphome-weather 7" display project (which previously sourced these from a
-- MeteobridgeSQL-based HA integration and has no equivalent today):
--
--   air_temp_high_today    MAX air temperature since local midnight
--   air_temp_low_today     MIN air temperature since local midnight
--   wind_speed_avg_10min   mean wind speed over the trailing 10 min
--
-- Same CONVERT_TZ/CROSS JOIN pattern as the existing wind_gust_high_today /
-- wind_bearing_avg_10min columns added in
-- migrations/20260703_add_combined_realtime_stats.sql — see that file for
-- the full rationale on the local-midnight boundary and the mysql.time_zone
-- prerequisite.
--
-- wind_speed_avg_10min fills a real gap, not just a rename: the Davis
-- receiver publishes wind_avg_ms as the raw per-packet instantaneous
-- reading (see davisnet-weatherlogger.yaml, "Wind (present in every
-- packet)" section — the ESPHome entity's 5-sample sliding-window filter
-- never makes it into the MQTT observation payload db_writer.py stores), so
-- despite its name there was previously no true rolling average of wind
-- speed anywhere in the schema. combined_realtime.wind_avg_ms already
-- serves as "last measured wind speed" as-is.
--
-- temp_humidity is the role air_temperature_c is sourced from (see
-- combined_realtime), same as wind_gust_high_today sources from the wind
-- role.

USE weatherdatalogger;

CREATE OR REPLACE VIEW combined_realtime_stats AS
SELECT
    gust.wind_gust_high_today,
    bday.wind_bearing_avg_day,
    b10.wind_bearing_avg_10min,
    rain.rain_total_yesterday,
    thigh.air_temp_high_today,
    tlow.air_temp_low_today,
    wavg.wind_speed_avg_10min
FROM
    (
        SELECT MAX(h.wind_gust_ms) AS wind_gust_high_today
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'wind')
          AND  h.recorded_at >= CONVERT_TZ(
                   DATE(CONVERT_TZ(UTC_TIMESTAMP(), 'UTC', 'Europe/Copenhagen')),
                   'Europe/Copenhagen', 'UTC')
    ) gust
CROSS JOIN
    (
        SELECT MOD(ROUND(DEGREES(ATAN2(
                   AVG(SIN(RADIANS(h.wind_direction_deg))),
                   AVG(COS(RADIANS(h.wind_direction_deg)))
               ))) + 360, 360) AS wind_bearing_avg_day
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'wind')
          AND  h.recorded_at >= CONVERT_TZ(
                   DATE(CONVERT_TZ(UTC_TIMESTAMP(), 'UTC', 'Europe/Copenhagen')),
                   'Europe/Copenhagen', 'UTC')
    ) bday
CROSS JOIN
    (
        SELECT MOD(ROUND(DEGREES(ATAN2(
                   AVG(SIN(RADIANS(h.wind_direction_deg))),
                   AVG(COS(RADIANS(h.wind_direction_deg)))
               ))) + 360, 360) AS wind_bearing_avg_10min
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'wind')
          AND  h.recorded_at >= UTC_TIMESTAMP() - INTERVAL 10 MINUTE
    ) b10
CROSS JOIN
    (
        SELECT MAX(h.rain_accumulation_mm) AS rain_total_yesterday
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'rain')
          AND  h.recorded_at >= CONVERT_TZ(
                   DATE(CONVERT_TZ(UTC_TIMESTAMP(), 'UTC', 'Europe/Copenhagen')) - INTERVAL 1 DAY,
                   'Europe/Copenhagen', 'UTC')
          AND  h.recorded_at <  CONVERT_TZ(
                   DATE(CONVERT_TZ(UTC_TIMESTAMP(), 'UTC', 'Europe/Copenhagen')),
                   'Europe/Copenhagen', 'UTC')
    ) rain
CROSS JOIN
    (
        SELECT MAX(h.air_temperature_c) AS air_temp_high_today
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'temp_humidity')
          AND  h.recorded_at >= CONVERT_TZ(
                   DATE(CONVERT_TZ(UTC_TIMESTAMP(), 'UTC', 'Europe/Copenhagen')),
                   'Europe/Copenhagen', 'UTC')
    ) thigh
CROSS JOIN
    (
        SELECT MIN(h.air_temperature_c) AS air_temp_low_today
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'temp_humidity')
          AND  h.recorded_at >= CONVERT_TZ(
                   DATE(CONVERT_TZ(UTC_TIMESTAMP(), 'UTC', 'Europe/Copenhagen')),
                   'Europe/Copenhagen', 'UTC')
    ) tlow
CROSS JOIN
    (
        SELECT AVG(h.wind_avg_ms) AS wind_speed_avg_10min
        FROM   history  h
        JOIN   stations s ON h.station_id = s.station_id
        WHERE  s.station_type = (SELECT station_type FROM station_roles WHERE role = 'wind')
          AND  h.recorded_at >= UTC_TIMESTAMP() - INTERVAL 10 MINUTE
    ) wavg;
