-- Migration: 20260702_add_rain_raw_log.sql
-- Temporary table for comparing the Davis ISS's raw RF tip-counter rain
-- value (davis_rain_raw, re-enabled in davis-vantage-receiver.yaml) against
-- the Meteobridge/console-corrected daily total already stored in
-- history.rain_accumulation_mm. Not tied to `stations` by FK — this is a
-- short-lived diagnostic capture, safe to drop once the comparison is done.

USE weatherdatalogger;

CREATE TABLE IF NOT EXISTS rain_raw_log (
    id             BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
    station_id     VARCHAR(32)      NOT NULL,
    recorded_at    DATETIME         NOT NULL,
    raw_tip_count  TINYINT UNSIGNED NOT NULL COMMENT 'Raw 0-127 tip counter exactly as decoded from the RF packet, unfiltered — ground truth for checking the delta/accumulation math against',
    rain_raw_mm    FLOAT            NOT NULL COMMENT 'Locally-accumulated raw RF tip-counter daily total (mm), derived from raw_tip_count by the on-device delta math, independent of Meteobridge corrections',
    PRIMARY KEY (id),
    KEY idx_rain_raw_log_station_time (station_id, recorded_at)
) ENGINE=InnoDB;
