-- Migration: 20260708_add_forecast_current_high_low.sql
-- forecast_current only stored the instantaneous current temperature —
-- Visual Crossing's currentConditions object has no high/low of its own.
-- visualcrossing_datalogger.py now fills temperature_high/temperature_low
-- from forecast_daily[0] (today's entry) alongside the current fetch, so
-- forecast_current can drive a "today's high/low" display without a
-- separate query against forecast_daily.

USE weatherdatalogger;

ALTER TABLE forecast_current
    ADD COLUMN IF NOT EXISTS temperature_high_c FLOAT NULL COMMENT "Today's forecast high — sourced from forecast_daily[0], not currentConditions" AFTER temperature_c,
    ADD COLUMN IF NOT EXISTS temperature_low_c  FLOAT NULL COMMENT "Today's forecast low — sourced from forecast_daily[0], not currentConditions" AFTER temperature_high_c;
