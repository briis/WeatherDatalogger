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

## [0.6.0] - 2026-07-23

### Added
- New optional 6th service: `weatherdatalogger/api/` — a FastAPI + uvicorn REST + WebSocket API providing read-only access to `combined_realtime`/`combined_realtime_stats`, for dashboards/apps that shouldn't need direct database or MQTT access. `GET /api/v1/current` for pull, `WS /api/v1/ws/current` for push (sends the snapshot on connect, then again on every change); both served from an in-memory cache refreshed by a background poller (`[api] poll_interval_s`, default 5s), so no request hits MariaDB directly. Interactive docs at `/docs`. Single shared-secret API key auth (`X-API-Key` header / `?api_key=` query param), its own SELECT-only `weatherdatalogger_api` database user (`database/04_create_api_readonly_user.sql` + `scripts/create_api_readonly_user.sh`, mirroring the existing `weatherdatalogger_ha` pattern), optional CORS. Off by default (`[api] enabled = false`); `install.sh`'s wizard offers to enable it, create the readonly user, and generate an API key. See `weatherdatalogger/api/README.md` for full usage, and `CONTEXT.md`/`AGENT.md` for the architecture

## [0.5.1] - 2026-07-22

### Fixed
- `[visualcrossing] language` config comments incorrectly said the setting was "unused" — that was true when the comment was written, but `forecast_current`/`forecast_daily`'s `description` narrative text (added in `migrations/20260713_add_forecast_description.sql`) is sent in whatever language `language` is set to (it's passed straight through as Visual Crossing's `lang` API parameter). No code change — `visualcrossing_datalogger.py` already forwarded it correctly. Set `language = da` (or any of `pyVisualCrossing.const.SUPPORTED_LANGUAGES`) in `config.ini` and restart `visualcrossing-datalogger` to change it

## [0.5.0] - 2026-07-22

### Added
- `database/migrations/20260722_add_daily_temp_extremes_and_wind_speed_avg.sql` — three new `combined_realtime_stats` columns, needed by downstream consumers (e.g. the [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) integration) that previously sourced them from a MeteobridgeSQL-based setup: `air_temp_high_today`/`air_temp_low_today` (max/min air temperature since local midnight, `temp_humidity` role) and `wind_speed_avg_10min` (genuine trailing 10-minute mean wind speed, `wind` role — unlike `combined_realtime.wind_avg_ms`, which for Davis is the raw per-packet instantaneous reading despite its name)

## [0.4.1] - 2026-07-20

### Changed
- `ESPHome/airquality/air-quality-monitor.yaml` now integrates with Home Assistant via ESPHome's own MQTT discovery (`mqtt: discovery: true`), matching the Davis receiver, instead of the native API — `api:` is now commented out by default (remote logs/OTA only) and `time:` switched from `homeassistant` to `sntp` so the data path stays independent of whether the device is ever added via HA's native ESPHome integration

## [0.4.0] - 2026-07-20

### Added
- `ESPHome/airquality/` — a new custom air quality monitor (ESP32-C6 + SDS011 PM2.5/PM10 + BME280), field-compatible with the Davis AirLink integration. Publishes to `weatherdatalogger/aqmonitor-<id>/observation` with `pm_2p5_ugm3`/`pm_10_ugm3`/`aqi_pm2p5`/`aqi_pm10`/`caqi_pm2p5`/`caqi_pm10`/`air_temperature_c`/`relative_humidity_pct`/`dew_point_c`/`station_pressure_mb` — reuses `db_writer.py`'s existing AirLink columns, no schema changes needed. See `ESPHome/airquality/README.md` for hardware, field-compatibility caveats (no PM1.0/rolling-average/NowCast on this hardware), and how to point the `air_quality` `station_roles` entry at it

### Changed
- **Breaking (repo layout, not runtime):** the Davis Vantage Vue ESPHome firmware moved from the top-level `davis/` directory to `ESPHome/davis/`, as a sibling of the new `ESPHome/airquality/`. `deploy.sh` and `ESPHome/davis/README.md`/`scripts/set_daily_rain.sh` updated for the new path. No effect on already-deployed installs — the moved files aren't part of the LXC deploy, only referenced from the repo for flashing

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
