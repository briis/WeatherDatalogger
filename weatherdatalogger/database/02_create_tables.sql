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

-- Maps each functional "role" (wind, pressure, ...) to the station_type that
-- currently supplies it. combined_realtime and evt_aggregate_history_charting
-- look this up at query time instead of hardcoding a literal station_type, so
-- installs without a Davis/Tempest/AirLink of a particular type can redirect
-- a role to whatever hardware they do have. See migrations/20260703_add_station_roles.sql
-- for the full role -> column mapping and how to reassign a role.
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
    wind_beaufort               TINYINT UNSIGNED NULL COMMENT '0-12 Beaufort force, derived from wind_avg_ms',
    wind_beaufort_description   VARCHAR(32)   NULL COMMENT 'Localized per the davis yaml `language` substitution (en/da)',
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
    battery_low                 BOOLEAN       NULL COMMENT 'Low battery flag (Davis)',
    -- indoor — Davis receiver's own BME280, co-located with the ESP32/CC1101
    -- (indoor temp/humidity; its pressure reading lives in station_pressure_mb
    -- above, alongside Tempest's, since both are the same column)
    indoor_temperature_c        FLOAT         NULL COMMENT 'Davis receiver BME280',
    indoor_humidity_pct         FLOAT         NULL COMMENT 'Davis receiver BME280',
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
    caqi_pm2p5                  SMALLINT UNSIGNED NULL COMMENT 'EU CAQI (CITEAIR) from current PM2.5',
    caqi_pm10                   SMALLINT UNSIGNED NULL COMMENT 'EU CAQI (CITEAIR) from current PM10',
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
    wind_beaufort               TINYINT UNSIGNED NULL,
    wind_beaufort_description   VARCHAR(32)   NULL,
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
    battery_low                 BOOLEAN       NULL,
    -- indoor — Davis receiver's own BME280, co-located with the ESP32/CC1101
    indoor_temperature_c        FLOAT         NULL,
    indoor_humidity_pct         FLOAT         NULL,
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
    caqi_pm2p5                  SMALLINT UNSIGNED NULL,
    caqi_pm10                   SMALLINT UNSIGNED NULL,
    PRIMARY KEY (id),
    KEY idx_history_station_time (station_id, recorded_at),
    CONSTRAINT fk_history_station
        FOREIGN KEY (station_id) REFERENCES stations (station_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─────────────────────────────────────────────────────────────────────────────
-- View: combined_realtime
-- Merges one row per configured role (wind, pressure, temp_humidity, solar_uv,
-- rain, lightning, air_quality) into a single row, sourcing each role from
-- whatever station_type station_roles currently maps it to (see that table's
-- comment, and migrations/20260703_add_station_roles.sql for the full
-- role -> column mapping and how to reassign a role). Column names are
-- role-based, not tied to any specific station make/model, so a role can be
-- reassigned to new hardware (including a station type added later) without
-- the column names becoming misleading.
-- `wind` is the mandatory anchor (INNER JOIN) — a setup with no station that
-- reports wind gets zero rows back regardless of role config.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW combined_realtime AS
SELECT
    -- Timestamps
    w.recorded_at                   AS recorded_at,
    pr.recorded_at                  AS data_recorded_at,
    aq.recorded_at                  AS air_quality_recorded_at,
    -- Wind
    w.wind_lull_ms,
    w.wind_avg_ms,
    w.wind_gust_ms,
    w.wind_direction_deg,
    w.wind_beaufort,
    w.wind_beaufort_description,
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
    th.battery_low,
    -- Indoor (the temp_humidity-role station's own onboard indoor sensor,
    -- co-located with its receiver, distinct from its outdoor sensor array)
    th.indoor_temperature_c,
    th.indoor_humidity_pct,
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
-- View: combined_realtime_stats
-- Derived/calculated stats computed on demand from the raw `history` table
-- (not history_charting, which is clock-bucketed with up to ~20 min lag and
-- too coarse for a rolling 10-minute average). `wind` and `rain` are sourced
-- via station_roles, same as combined_realtime.
-- Timezone: recorded_at is stored as naive UTC; "today"/"yesterday" mean the
-- calendar day in Europe/Copenhagen, so the day boundary is computed via
-- CONVERT_TZ. CONVERT_TZ with a named zone requires the mysql.time_zone
-- tables to be loaded — if empty, it silently returns NULL. One-time fix:
--   mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root mysql
-- See migrations/20260703_add_combined_realtime_stats.sql for full detail.
-- ─────────────────────────────────────────────────────────────────────────────
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

-- ─────────────────────────────────────────────────────────────────────────────
-- Table: history_charting
-- Pre-aggregated 10-minute windows combining all station types.
-- One combined row per window_start (clock-aligned UTC: 00:00, 00:10, …).
-- Populated by the evt_aggregate_history_charting event below.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS history_charting (
    id                          BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    window_start                DATETIME          NOT NULL COMMENT '10-min boundary UTC (floor)',

    -- Wind (Davis) — lull=MIN, avg=AVG, gust=MAX, dir=circular AVG
    wind_lull_ms                FLOAT             NULL,
    wind_avg_ms                 FLOAT             NULL,
    wind_gust_ms                FLOAT             NULL,
    wind_direction_deg          SMALLINT UNSIGNED NULL,
    -- Beaufort/description = last value in window, same convention as
    -- pressure_trend below (an ordinal/text pair isn't meaningful averaged)
    wind_beaufort               TINYINT UNSIGNED NULL,
    wind_beaufort_description   VARCHAR(32)       NULL,

    -- Pressure (`pressure` role, e.g. Tempest — has trend/sea-level data the
    -- Davis receiver's on-board BME280 doesn't compute) — AVG; trend text =
    -- last value in window
    station_pressure_mb         FLOAT             NULL,
    sea_level_pressure_mb       FLOAT             NULL,
    pressure_trend_mb           FLOAT             NULL,
    pressure_trend              VARCHAR(16)       NULL,
    sea_level_pressure_trend_mb FLOAT             NULL,
    sea_level_pressure_trend    VARCHAR(16)       NULL,

    -- Temperature & humidity (Davis, except wet bulb / delta T which stay Tempest) — AVG
    air_temperature_c           FLOAT             NULL,
    relative_humidity_pct       FLOAT             NULL,
    dew_point_c                 FLOAT             NULL,
    wet_bulb_c                  FLOAT             NULL,
    delta_t_c                   FLOAT             NULL,
    feels_like_c                FLOAT             NULL,
    heat_index_c                FLOAT             NULL,
    wind_chill_c                FLOAT             NULL,

    -- Solar & UV (Tempest — no sensor fitted on the Davis ISS) — AVG
    illuminance_lux             INT UNSIGNED      NULL,
    uv_index                    FLOAT             NULL,
    solar_radiation_wm2         FLOAT             NULL,

    -- Rain (Davis) — accumulation=MAX (cumulative "so far today" counter,
    -- not a per-observation delta — see migrations/20260703_fix_charting_rain_cumulative.sql), rate=MAX
    rain_accumulation_mm        FLOAT             NULL,
    rain_rate_mmh               FLOAT             NULL,

    -- Lightning (Tempest — Davis has no lightning detector)
    lightning_last_detected     DATETIME          NULL,
    lightning_count_3h          SMALLINT UNSIGNED NULL,
    lightning_min_dist_3h_km    FLOAT             NULL,
    lightning_max_dist_3h_km    FLOAT             NULL,

    -- Air properties — vapor pressure (Davis) / air density (Tempest) — AVG
    vapor_pressure_mb           FLOAT             NULL,
    air_density_kgm3            FLOAT             NULL,

    -- Device
    battery_volts               FLOAT             NULL,
    battery_low                 BOOLEAN           NULL COMMENT 'temp_humidity-role low-battery flag',

    -- Indoor (the temp_humidity-role station's own onboard indoor sensor) — AVG
    indoor_temperature_c        FLOAT             NULL,
    indoor_humidity_pct         FLOAT             NULL,

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
    caqi_pm2p5                  SMALLINT UNSIGNED NULL,
    caqi_pm10                   SMALLINT UNSIGNED NULL,

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
-- Role -> station_type is resolved once per run via a CROSS JOIN against a
-- single pivoted row (roles) from station_roles, rather than hardcoding a
-- literal station_type in every CASE WHEN. See station_roles' comment and
-- migrations/20260703_add_station_roles.sql for the full role -> column
-- mapping and how to reassign a role.
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
        wind_beaufort,
        wind_beaufort_description,
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
        battery_low,
        indoor_temperature_c,
        indoor_humidity_pct,
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
        -- Beaufort/description — last value in window (an ordinal/text
        -- pair isn't meaningful averaged), same convention as pressure_trend below
        CAST(SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = roles.wind_type THEN wind_beaufort END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1) AS UNSIGNED),
        SUBSTRING_INDEX(GROUP_CONCAT(
            CASE WHEN station_type = roles.wind_type THEN wind_beaufort_description END
            ORDER BY recorded_at DESC SEPARATOR '\x1F'
        ), '\x1F', 1),
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
        -- Indoor (the temp_humidity-role station's own onboard indoor
        -- sensor) — AVG
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN indoor_temperature_c END),
        AVG(CASE WHEN station_type = roles.temp_humidity_type THEN indoor_humidity_pct END),
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

-- ─────────────────────────────────────────────────────────────────────────────
-- Forecast tables — Visual Crossing Timeline Weather API data, fetched and
-- published to MQTT by visualcrossing_datalogger.py (topics
-- weatherdatalogger/forecast-<provider>-<location>/{current,forecast_hourly,
-- forecast_daily}), written here by db_writer.py. All three hold only the
-- latest fetch per (provider, location) — not an append-only history —
-- since nothing currently needs to track how a forecast for a given
-- hour/day changed across successive fetches, just the current best guess
-- for driving a Home Assistant weather entity. `location` matches the
-- `location` config value in the provider's own config section (e.g.
-- [visualcrossing], defaults to "home"), not a `stations` row — forecasts
-- aren't tied to a physical device the way `realtime`/`history` are.
--
-- `provider` is a forecast source slug (e.g. "visualcrossing"), hardcoded
-- per forecast-datalogger script as its own FORECAST_PROVIDER constant —
-- see visualcrossing_datalogger.py. It lets a second forecast provider
-- (e.g. Pirate Weather, WeatherFlow Better Forecast) coexist against the
-- same `location` without colliding on the same row/topic — see
-- migrations/20260713_add_forecast_provider.sql for why this was added
-- after the fact (originally these tables assumed Visual Crossing would be
-- the only forecast source, keyed on `location` alone).
--
-- (This previously held the WeatherFlow Better Forecast API's data, sourced
-- from tempest_datalogger.py's forecast thread — replaced entirely, not
-- extended, since Visual Crossing is a richer superset covering the same
-- ground: feels_like/cloud_cover/wind_gust/uv_index are new here.)
--
-- snow_cm/snow_depth_cm/precipitation_type/solar_energy_mjm2/severe_risk/
-- sunrise/sunset/moon_phase/precipitation_cover_pct were added once
-- pyVisualCrossing 1.0.2 started exposing them (earlier versions parsed a
-- narrower field set from the same API response) — see
-- migrations/20260708_add_visualcrossing_extra_fields.sql.
--
-- forecast_current.temperature_high_c/temperature_low_c were added since
-- Visual Crossing's currentConditions has no high/low of its own —
-- visualcrossing_datalogger.py fills them from forecast_daily[0] instead —
-- see migrations/20260708_add_forecast_current_high_low.sql.
--
-- description was added to forecast_current (the API's top-level narrative
-- summary of the whole forecast period, e.g. "Similar temperatures
-- continuing with a chance of rain") and forecast_daily (per-day narrative,
-- e.g. "Cloudy throughout the day with rain in the morning"). The top-level
-- one is exposed by pyVisualCrossing as ForecastData.description; the
-- per-day one isn't parsed by the wrapper at all, so
-- visualcrossing_datalogger.py reads it straight off the raw API response —
-- see migrations/20260713_add_forecast_description.sql.
-- ─────────────────────────────────────────────────────────────────────────────

-- One row per (provider, location), upserted on every fetch (like `realtime`).
CREATE TABLE IF NOT EXISTS forecast_current (
    provider             VARCHAR(32)       NOT NULL COMMENT 'Forecast provider slug, e.g. visualcrossing — matches the MQTT topic segment forecast-<provider>-<location>',
    location             VARCHAR(64)       NOT NULL,
    fetched_at           DATETIME          NOT NULL,
    weather_condition    VARCHAR(32)       NULL COMMENT 'HA weather condition, e.g. partlycloudy — `condition` is a reserved word in MariaDB',
    temperature_c        FLOAT             NULL,
    temperature_high_c   FLOAT             NULL COMMENT "Today's forecast high — sourced from forecast_daily[0], not currentConditions",
    temperature_low_c    FLOAT             NULL COMMENT "Today's forecast low — sourced from forecast_daily[0], not currentConditions",
    feels_like_c         FLOAT             NULL,
    humidity_pct         FLOAT             NULL,
    dew_point_c          FLOAT             NULL,
    wind_speed_ms        FLOAT             NULL,
    wind_gust_ms         FLOAT             NULL,
    wind_bearing_deg     SMALLINT UNSIGNED NULL,
    pressure_mb          FLOAT             NULL COMMENT 'Sea-level pressure',
    cloud_cover_pct      TINYINT UNSIGNED  NULL,
    uv_index             FLOAT             NULL,
    visibility_km        TINYINT UNSIGNED  NULL,
    solar_radiation_wm2  FLOAT             NULL,
    solar_energy_mjm2    FLOAT             NULL,
    snow_cm              FLOAT             NULL,
    snow_depth_cm        FLOAT             NULL,
    precipitation_type   VARCHAR(64)       NULL COMMENT 'Comma-joined, e.g. rain,ice — pyVisualCrossing returns a list',
    sunrise              VARCHAR(32)       NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type',
    sunset               VARCHAR(32)       NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type',
    moon_phase           FLOAT             NULL COMMENT 'Fraction 0-1 (0/1 = new moon, 0.5 = full moon)',
    description          VARCHAR(255)      NULL COMMENT 'Narrative summary of the whole forecast period, from the API response top level',
    PRIMARY KEY (provider, location)
) ENGINE=InnoDB;

-- One row per (provider, location, forecast_time); each fetch replaces the
-- full set for that provider+location (see db_writer.py) so hours that drop
-- out of the forecast window don't linger. No sunrise/sunset/moon_phase —
-- Visual Crossing only reports those for current conditions and daily
-- entries.
CREATE TABLE IF NOT EXISTS forecast_hourly (
    id                             BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    provider                       VARCHAR(32)       NOT NULL COMMENT 'Forecast provider slug, e.g. visualcrossing — matches the MQTT topic segment forecast-<provider>-<location>',
    location                       VARCHAR(64)       NOT NULL,
    forecast_time                  DATETIME          NOT NULL COMMENT 'UTC hour this row forecasts',
    fetched_at                     DATETIME          NOT NULL,
    weather_condition              VARCHAR(32)       NULL,
    temperature_c                  FLOAT             NULL,
    feels_like_c                   FLOAT             NULL,
    humidity_pct                   FLOAT             NULL,
    dew_point_c                    FLOAT             NULL,
    wind_speed_ms                  FLOAT             NULL,
    wind_gust_ms                   FLOAT             NULL,
    wind_bearing_deg               SMALLINT UNSIGNED NULL,
    pressure_mb                    FLOAT             NULL,
    cloud_cover_pct                TINYINT UNSIGNED  NULL,
    uv_index                       FLOAT             NULL,
    precipitation_mm               FLOAT             NULL,
    precipitation_probability_pct  TINYINT UNSIGNED  NULL,
    visibility_km                  TINYINT UNSIGNED  NULL,
    solar_radiation_wm2            FLOAT             NULL,
    solar_energy_mjm2              FLOAT             NULL,
    severe_risk                    FLOAT             NULL COMMENT 'Risk score of severe weather, per Visual Crossing',
    snow_cm                        FLOAT             NULL,
    snow_depth_cm                  FLOAT             NULL,
    precipitation_type             VARCHAR(64)       NULL COMMENT 'Comma-joined, e.g. rain,ice — pyVisualCrossing returns a list',
    PRIMARY KEY (id),
    UNIQUE KEY uq_forecast_hourly (provider, location, forecast_time)
) ENGINE=InnoDB;

-- One row per (provider, location, forecast_time); same replace-on-fetch
-- approach as forecast_hourly. temperature_high_c/temperature_low_c replace
-- a single temperature_c column since a daily forecast is a high/low pair,
-- not one instant reading. No visibility_km — Visual Crossing's daily
-- entries don't report it (only current conditions and hourly do).
CREATE TABLE IF NOT EXISTS forecast_daily (
    id                             BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    provider                       VARCHAR(32)       NOT NULL COMMENT 'Forecast provider slug, e.g. visualcrossing — matches the MQTT topic segment forecast-<provider>-<location>',
    location                       VARCHAR(64)       NOT NULL,
    forecast_time                  DATETIME          NOT NULL COMMENT 'Day this row forecasts (as reported by the API — see Visual Crossing day datetime)',
    fetched_at                     DATETIME          NOT NULL,
    weather_condition              VARCHAR(32)       NULL,
    temperature_high_c             FLOAT             NULL,
    temperature_low_c              FLOAT             NULL,
    feels_like_c                   FLOAT             NULL,
    humidity_pct                   FLOAT             NULL,
    dew_point_c                    FLOAT             NULL,
    wind_speed_ms                  FLOAT             NULL,
    wind_gust_ms                   FLOAT             NULL,
    wind_bearing_deg               SMALLINT UNSIGNED NULL,
    pressure_mb                    FLOAT             NULL,
    cloud_cover_pct                TINYINT UNSIGNED  NULL,
    uv_index                       FLOAT             NULL,
    precipitation_mm               FLOAT             NULL,
    precipitation_probability_pct  TINYINT UNSIGNED  NULL,
    precipitation_cover_pct        TINYINT UNSIGNED  NULL COMMENT 'Percentage of the day with precipitation',
    solar_radiation_wm2            FLOAT             NULL,
    solar_energy_mjm2              FLOAT             NULL,
    severe_risk                    FLOAT             NULL COMMENT 'Risk score of severe weather, per Visual Crossing',
    snow_cm                        FLOAT             NULL,
    snow_depth_cm                  FLOAT             NULL,
    precipitation_type             VARCHAR(64)       NULL COMMENT 'Comma-joined, e.g. rain,ice — pyVisualCrossing returns a list',
    sunrise                        VARCHAR(32)       NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type',
    sunset                         VARCHAR(32)       NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type',
    moon_phase                     FLOAT             NULL COMMENT 'Fraction 0-1 (0/1 = new moon, 0.5 = full moon)',
    description                    VARCHAR(255)      NULL COMMENT 'Narrative summary of this specific day, from the API response (not parsed by pyVisualCrossing — read from the raw JSON)',
    PRIMARY KEY (id),
    UNIQUE KEY uq_forecast_daily (provider, location, forecast_time)
) ENGINE=InnoDB;
