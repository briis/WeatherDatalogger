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

## [0.3.0] - 2026-07-13

### Added
- `scripts/create_ha_readonly_user.sh` + `database/03_create_readonly_user.sql` — creates a `SELECT`-only `weatherdatalogger_ha` MariaDB user for the separate [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) Home Assistant integration, which reads this database directly. The script is idempotent (leaves an existing user's password alone) and prompts for the password rather than generating one, since it has to be re-entered into the other project's config flow anyway. `install.sh`'s setup wizard offers to run it once, at first-time setup, if you say you're using that integration; otherwise it's runnable standalone anytime later
- `install.sh`'s secret-valued prompts (MQTT password, Visual Crossing API key) now use hidden input (`read -s`) instead of echoing what you type

## [0.2.0] - 2026-07-13

### Added
- `scripts/install.sh` — one-time (but safely re-runnable) fresh-host bootstrap: OS packages, service user, MariaDB (network access + event scheduler), database + application user (password auto-generated), schema creation, and a short interactive setup wizard (MQTT broker, which stations/forecast provider you have) that writes `config.ini` for you. Skipped entirely if `config.ini` already exists, so a re-run never overwrites your settings
- `## Overview` section in `README.md` — system requirements and a supported-stations/forecast-providers summary, up front before the detailed service tables

### Changed
- `deploy.sh`'s service restart step is now config-driven instead of systemd-driven: a service whose `config.ini` section says `enabled = true` (or, for `weatherdb-writer`, just `config.ini` existing) gets `systemctl enable`d automatically if it wasn't already, then restarted — no more manual `systemctl enable --now` per service after editing `config.ini`. It never works the other way: a running service whose config now says `false` is left alone, not stopped
- `README.md`'s Installation section now leads with the one-command `install.sh` flow; the previous 10 manual steps are kept as a collapsed "Manual installation (troubleshooting / customizing)" reference rather than the primary path

## [0.1.0] - 2026-07-13

### Added
- `provider` dimension on `forecast_current`/`forecast_hourly`/`forecast_daily` (schema, MQTT topic shape `forecast-<provider>-<location>/...`, and `db_writer.py`'s parsing/writer/upsert logic) so more than one forecast provider can run concurrently against the same `location` without colliding. Visual Crossing's own provider slug is `visualcrossing`, set via `FORECAST_PROVIDER` in `visualcrossing_datalogger.py`
- `description` narrative-summary field on Visual Crossing's `forecast_current` (whole-period summary) and `forecast_daily` (per-day summary) rows
- `VERSION` file (repo root) plus version tracking in `deploy.sh` — see above

### Changed
- **Breaking:** Tempest, AirLink, and Meteobridge now require an explicit `enabled = true` in their own `config.ini` section before they'll run, matching how Visual Crossing already worked. Previously Tempest always ran, and AirLink/Meteobridge inferred enablement from whether `host` was set. Existing deployments get a one-time `WARNING` in that service's journal (`[<service>] enabled is not set in config.ini — defaulting to disabled...`) and idle until `enabled = true` is added
- `deploy.sh`'s restart step now also checks each service's config-level `enabled` flag (not just `systemctl is-enabled`) — a config-disabled service is skipped rather than restarted, since it would just idle back down
- Repository visibility changed from private to public; `deploy.sh` clones over HTTPS instead of requiring an SSH deploy key
