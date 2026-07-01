-- Migration: 20260701_add_battery_low.sql
-- Add a battery_low column for the Davis Vantage ISS, which only transmits a
-- boolean low-battery flag (no voltage reading, unlike Tempest's battery_volts).
-- NULL for all other station types.

USE weatherdatalogger;

ALTER TABLE realtime
    ADD COLUMN IF NOT EXISTS battery_low BOOLEAN NULL COMMENT 'Low battery flag (Davis)' AFTER battery_volts;

ALTER TABLE history
    ADD COLUMN IF NOT EXISTS battery_low BOOLEAN NULL COMMENT 'Low battery flag (Davis)' AFTER battery_volts;
