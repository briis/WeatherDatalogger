-- Migration: 20261009_add_history_recorded_at_index.sql
-- Adds a time-only index on history.recorded_at.
--
-- Why: combined_realtime_stats (see
-- migrations/20260703_add_combined_realtime_stats.sql and
-- 20260722_add_daily_temp_extremes_and_wind_speed_avg.sql) resolves each
-- role's station by JOINing history to stations on station_id, then filters
-- on a recorded_at window ("since local midnight", "last 10 minutes", ...).
-- With only idx_history_station_time (station_id, recorded_at) available,
-- MariaDB plans that join as a `ref` lookup on station_id alone — the
-- recorded_at half of the index can't be used as a range bound when
-- station_id comes from a join rather than a constant — and then walks
-- every index entry that station has ever written, checking recorded_at
-- one by one ("Using index condition"). That happens once per subquery,
-- seven times per SELECT on the view.
--
-- So the view's cost grew with the total size of history instead of with
-- the size of its time windows. The Davis receiver publishes an
-- /observation on every RF packet (~every 2.5 s, ~34k rows/day), so after
-- about three months a single SELECT * FROM combined_realtime_stats took
-- several seconds — long enough to trip the 10 s read timeout in the
-- WeatherDatalogger-HA integration:
--   (2013, 'Lost connection to MySQL server during query (The read
--   operation timed out)')
-- which marks every entity of that integration unavailable until the next
-- successful poll. The optional API service (api_server.py) runs the same
-- view every poll_interval_s (default 5 s), adding to the load.
--
-- With idx_history_recorded_at the optimizer drives each subquery from a
-- range scan on recorded_at instead and only reads the rows inside the
-- window. Measured on MariaDB 10.11 with ~3.5M history rows: ~5 s -> ~0.15 s
-- for the whole view, same result values. No view or code changes needed.
--
-- IF NOT EXISTS keeps this idempotent on a fresh install, where
-- 02_create_tables.sql already created the index. InnoDB builds the index
-- in place — db_writer.py can keep inserting while it runs (a few seconds
-- per few million rows).

USE weatherdatalogger;

ALTER TABLE history
    ADD INDEX IF NOT EXISTS idx_history_recorded_at (recorded_at);
