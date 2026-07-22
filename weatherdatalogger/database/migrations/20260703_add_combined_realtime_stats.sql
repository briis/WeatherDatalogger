-- Migration: 20260703_add_combined_realtime_stats.sql
-- Adds a new view, combined_realtime_stats, with derived/calculated stats
-- computed on demand from the raw `history` table (not history_charting,
-- which is clock-bucketed with up to ~20 min lag and too coarse for a
-- rolling 10-minute average):
--
--   wind_gust_high_today   MAX wind gust since local midnight
--   wind_bearing_avg_day   circular-mean wind bearing since local midnight
--   wind_bearing_avg_10min circular-mean wind bearing over the trailing 10 min
--   rain_total_yesterday   final rain accumulation for the full previous local day
--
-- rain_accumulation_mm is NOT a per-observation delta — per davis/README.md
-- it's a running cumulative "rain so far today" counter, republished
-- unchanged on every packet and reset to 0 at local midnight (see
-- davis-vantage-receiver.yaml's on_time trigger / Meteobridge daysum
-- template). So rain_total_yesterday is computed as MAX(rain_accumulation_mm)
-- over yesterday's rows, not SUM — the max value recorded on a given local
-- day is that day's final total, since the counter only resets at the day
-- boundary. Summing would double/triple/…-count the same running total
-- across every observation in the window.
--
-- `wind` and `rain` are sourced via station_roles, same as combined_realtime
-- (see migrations/20260703_add_station_roles.sql), so reassigning a role
-- there also redirects these stats.
--
-- Timezone: recorded_at is stored as naive UTC (see 02_create_tables.sql and
-- migrations/20260701_fix_charting_event_timezone.sql for the incident where
-- mixing local-time functions with UTC-stored data silently broke a query).
-- "Today"/"yesterday" here mean the calendar day in Europe/Copenhagen, so the
-- UTC day boundary is computed via CONVERT_TZ rather than truncating
-- UTC_TIMESTAMP() directly. CONVERT_TZ with a named zone (as opposed to a
-- fixed '+02:00' offset) requires the mysql.time_zone tables to be loaded —
-- if they're empty, CONVERT_TZ silently returns NULL and the four columns
-- below will all read NULL instead of erroring. install.sh now does this
-- automatically (step 5b); one-time fix on an existing DB host:
--   mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root mysql
--   (older systems: mysql_tzinfo_to_sql ... | mysql -u root mysql)
--   (then restart mariadbd)
-- The 10-minute rolling average does not depend on local day boundaries, so
-- it's unaffected either way.

USE weatherdatalogger;

CREATE OR REPLACE VIEW combined_realtime_stats AS
SELECT
    gust.wind_gust_high_today,
    bday.wind_bearing_avg_day,
    b10.wind_bearing_avg_10min,
    rain.rain_total_yesterday
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
    ) rain;
