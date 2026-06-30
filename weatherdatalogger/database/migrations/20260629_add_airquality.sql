-- Migration: 20260629_add_airquality.sql
-- Add air quality columns (PM1/PM2.5/PM10/AQI) for the Davis AirLink sensor.
-- Columns are NULL for all non-AirLink stations.

USE weatherdatalogger;

ALTER TABLE realtime
    ADD COLUMN IF NOT EXISTS pm_1_ugm3           FLOAT            NULL COMMENT 'PM1.0 2-min avg µg/m³'      AFTER battery_volts,
    ADD COLUMN IF NOT EXISTS pm_2p5_ugm3         FLOAT            NULL COMMENT 'PM2.5 2-min avg µg/m³'      AFTER pm_1_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_1h_ugm3      FLOAT            NULL COMMENT 'PM2.5 1-hour avg µg/m³'     AFTER pm_2p5_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_3h_ugm3      FLOAT            NULL COMMENT 'PM2.5 3-hour avg µg/m³'     AFTER pm_2p5_1h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_24h_ugm3     FLOAT            NULL COMMENT 'PM2.5 24-hour avg µg/m³'    AFTER pm_2p5_3h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_nowcast_ugm3 FLOAT            NULL COMMENT 'PM2.5 NowCast µg/m³'        AFTER pm_2p5_24h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_ugm3          FLOAT            NULL COMMENT 'PM10 2-min avg µg/m³'       AFTER pm_2p5_nowcast_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_1h_ugm3       FLOAT            NULL COMMENT 'PM10 1-hour avg µg/m³'      AFTER pm_10_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_3h_ugm3       FLOAT            NULL COMMENT 'PM10 3-hour avg µg/m³'      AFTER pm_10_1h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_24h_ugm3      FLOAT            NULL COMMENT 'PM10 24-hour avg µg/m³'     AFTER pm_10_3h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_nowcast_ugm3  FLOAT            NULL COMMENT 'PM10 NowCast µg/m³'         AFTER pm_10_24h_ugm3,
    ADD COLUMN IF NOT EXISTS aqi_pm2p5           SMALLINT UNSIGNED NULL COMMENT 'US EPA AQI from PM2.5 NowCast' AFTER pm_10_nowcast_ugm3,
    ADD COLUMN IF NOT EXISTS aqi_pm10            SMALLINT UNSIGNED NULL COMMENT 'US EPA AQI from PM10 NowCast'  AFTER aqi_pm2p5;

ALTER TABLE history
    ADD COLUMN IF NOT EXISTS pm_1_ugm3           FLOAT            NULL AFTER battery_volts,
    ADD COLUMN IF NOT EXISTS pm_2p5_ugm3         FLOAT            NULL AFTER pm_1_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_1h_ugm3      FLOAT            NULL AFTER pm_2p5_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_3h_ugm3      FLOAT            NULL AFTER pm_2p5_1h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_24h_ugm3     FLOAT            NULL AFTER pm_2p5_3h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_2p5_nowcast_ugm3 FLOAT            NULL AFTER pm_2p5_24h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_ugm3          FLOAT            NULL AFTER pm_2p5_nowcast_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_1h_ugm3       FLOAT            NULL AFTER pm_10_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_3h_ugm3       FLOAT            NULL AFTER pm_10_1h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_24h_ugm3      FLOAT            NULL AFTER pm_10_3h_ugm3,
    ADD COLUMN IF NOT EXISTS pm_10_nowcast_ugm3  FLOAT            NULL AFTER pm_10_24h_ugm3,
    ADD COLUMN IF NOT EXISTS aqi_pm2p5           SMALLINT UNSIGNED NULL AFTER pm_10_nowcast_ugm3,
    ADD COLUMN IF NOT EXISTS aqi_pm10            SMALLINT UNSIGNED NULL AFTER aqi_pm2p5;
