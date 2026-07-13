-- Migration: 20260713_add_forecast_description.sql
-- Adds the Visual Crossing API's narrative `description` text to
-- forecast_current (top-level summary of the whole forecast period) and
-- forecast_daily (per-day summary). Not added to forecast_hourly — Visual
-- Crossing doesn't report a description at hourly granularity.
--
-- The top-level description is exposed by pyVisualCrossing as
-- ForecastData.description (api.py already does
-- `api_result.get("description", "")` and passes it through), so
-- visualcrossing_datalogger.py's current payload can read it directly. The
-- per-day description is NOT parsed by pyVisualCrossing at all — its
-- ForecastDailyData has no such field — so visualcrossing_datalogger.py
-- reads it straight off the raw API response instead, the same way
-- _log_raw_response() already reaches into VisualCrossing._json_data.

USE weatherdatalogger;

ALTER TABLE forecast_current
    ADD COLUMN IF NOT EXISTS description VARCHAR(255) NULL COMMENT 'Narrative summary of the whole forecast period, from the API response top level' AFTER moon_phase;

ALTER TABLE forecast_daily
    ADD COLUMN IF NOT EXISTS description VARCHAR(255) NULL COMMENT 'Narrative summary of this specific day, from the API response (not parsed by pyVisualCrossing — read from the raw JSON)' AFTER moon_phase;
