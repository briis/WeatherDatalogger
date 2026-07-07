-- Migration: 20260708_add_visualcrossing_extra_fields.sql
-- pyVisualCrossing 1.0.2 started exposing several fields it previously
-- parsed off the same Visual Crossing API response but never surfaced on
-- the data objects: snow, snow_depth, precipitation_type, solar_energy,
-- severe_risk, sunrise/sunset, moon_phase, precipitation_cover (daily only).
-- It also widened solar_radiation and visibility to hourly (previously
-- current-conditions only). This adds the corresponding columns to
-- forecast_current/forecast_hourly/forecast_daily — see
-- visualcrossing_datalogger.py's payload builders and db_writer.py's
-- _FORECAST_*_FIELDS for the mapping.
--
-- precipitation_type is a list in the API/wrapper (e.g. ["rain", "ice"]);
-- stored here as a comma-joined VARCHAR, not a separate table — it's at
-- most 2-3 short values, not worth a normalized join for this.

USE weatherdatalogger;

ALTER TABLE forecast_current
    ADD COLUMN IF NOT EXISTS solar_energy_mjm2  FLOAT       NULL AFTER solar_radiation_wm2,
    ADD COLUMN IF NOT EXISTS snow_cm             FLOAT       NULL AFTER solar_energy_mjm2,
    ADD COLUMN IF NOT EXISTS snow_depth_cm       FLOAT       NULL AFTER snow_cm,
    ADD COLUMN IF NOT EXISTS precipitation_type  VARCHAR(64) NULL COMMENT 'Comma-joined, e.g. rain,ice — pyVisualCrossing returns a list' AFTER snow_depth_cm,
    ADD COLUMN IF NOT EXISTS sunrise             VARCHAR(32) NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type' AFTER precipitation_type,
    ADD COLUMN IF NOT EXISTS sunset              VARCHAR(32) NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type' AFTER sunrise,
    ADD COLUMN IF NOT EXISTS moon_phase          FLOAT       NULL COMMENT 'Fraction 0-1 (0/1 = new moon, 0.5 = full moon)' AFTER sunset;

ALTER TABLE forecast_hourly
    ADD COLUMN IF NOT EXISTS visibility_km       TINYINT UNSIGNED NULL AFTER precipitation_probability_pct,
    ADD COLUMN IF NOT EXISTS solar_radiation_wm2 FLOAT            NULL AFTER visibility_km,
    ADD COLUMN IF NOT EXISTS solar_energy_mjm2   FLOAT            NULL AFTER solar_radiation_wm2,
    ADD COLUMN IF NOT EXISTS severe_risk         FLOAT            NULL COMMENT 'Risk score of severe weather, per Visual Crossing' AFTER solar_energy_mjm2,
    ADD COLUMN IF NOT EXISTS snow_cm             FLOAT            NULL AFTER severe_risk,
    ADD COLUMN IF NOT EXISTS snow_depth_cm       FLOAT            NULL AFTER snow_cm,
    ADD COLUMN IF NOT EXISTS precipitation_type  VARCHAR(64)      NULL COMMENT 'Comma-joined, e.g. rain,ice — pyVisualCrossing returns a list' AFTER snow_depth_cm;

ALTER TABLE forecast_daily
    ADD COLUMN IF NOT EXISTS precipitation_cover_pct TINYINT UNSIGNED NULL COMMENT 'Percentage of the day with precipitation' AFTER precipitation_probability_pct,
    ADD COLUMN IF NOT EXISTS solar_radiation_wm2     FLOAT            NULL AFTER precipitation_cover_pct,
    ADD COLUMN IF NOT EXISTS solar_energy_mjm2       FLOAT            NULL AFTER solar_radiation_wm2,
    ADD COLUMN IF NOT EXISTS severe_risk             FLOAT            NULL COMMENT 'Risk score of severe weather, per Visual Crossing' AFTER solar_energy_mjm2,
    ADD COLUMN IF NOT EXISTS snow_cm                 FLOAT            NULL AFTER severe_risk,
    ADD COLUMN IF NOT EXISTS snow_depth_cm           FLOAT            NULL AFTER snow_cm,
    ADD COLUMN IF NOT EXISTS precipitation_type      VARCHAR(64)      NULL COMMENT 'Comma-joined, e.g. rain,ice — pyVisualCrossing returns a list' AFTER snow_depth_cm,
    ADD COLUMN IF NOT EXISTS sunrise                 VARCHAR(32)      NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type' AFTER precipitation_type,
    ADD COLUMN IF NOT EXISTS sunset                  VARCHAR(32)      NULL COMMENT 'Raw pass-through string from the API — pyVisualCrossing does not parse it to a time type' AFTER sunrise,
    ADD COLUMN IF NOT EXISTS moon_phase              FLOAT            NULL COMMENT 'Fraction 0-1 (0/1 = new moon, 0.5 = full moon)' AFTER sunset;
