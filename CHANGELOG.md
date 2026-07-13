# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
version numbers match the `VERSION` file at the repo root, which
`deploy.sh` records (alongside the deployed commit's short SHA) to
`/opt/weatherdatalogger/VERSION` on every deploy — `cat` that file to see
what's installed, and quote it when asking for a change or filing an issue.

This changelog starts at `0.1.0`, the first version tracked this way —
earlier history isn't backfilled entry-by-entry here; see `git log` for that.

## [Unreleased]

## [0.1.0] - 2026-07-13

### Added
- `provider` dimension on `forecast_current`/`forecast_hourly`/`forecast_daily` (schema, MQTT topic shape `forecast-<provider>-<location>/...`, and `db_writer.py`'s parsing/writer/upsert logic) so more than one forecast provider can run concurrently against the same `location` without colliding. Visual Crossing's own provider slug is `visualcrossing`, set via `FORECAST_PROVIDER` in `visualcrossing_datalogger.py`
- `description` narrative-summary field on Visual Crossing's `forecast_current` (whole-period summary) and `forecast_daily` (per-day summary) rows
- `VERSION` file (repo root) plus version tracking in `deploy.sh` — see above

### Changed
- **Breaking:** Tempest, AirLink, and Meteobridge now require an explicit `enabled = true` in their own `config.ini` section before they'll run, matching how Visual Crossing already worked. Previously Tempest always ran, and AirLink/Meteobridge inferred enablement from whether `host` was set. Existing deployments get a one-time `WARNING` in that service's journal (`[<service>] enabled is not set in config.ini — defaulting to disabled...`) and idle until `enabled = true` is added
- `deploy.sh`'s restart step now also checks each service's config-level `enabled` flag (not just `systemctl is-enabled`) — a config-disabled service is skipped rather than restarted, since it would just idle back down
- Repository visibility changed from private to public; `deploy.sh` clones over HTTPS instead of requiring an SSH deploy key
