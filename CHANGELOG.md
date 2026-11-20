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

### Added
- `web/` 0.5.0 — radar nowcast: the radar worker (0.2.0) tracks the rain's motion between the two newest frames (FFT cross-correlation with a fixed-echo mask, ported from the pydmi spike), estimates when rain reaches the station (up to 2 h), the nearest rain and its direction, and extrapolates the newest frame to 6 forecast frames for the next hour. Nedbør and radar widgets show e.g. "Regn ventes om ca. 25 min."; the radar popup plays the last 2 h followed by the next hour (marked as forecast). State between runs in `/var/lib/weather-web/radar-state/`
- `web/` 0.4.0 (phase 4 — popups): every widget opens a detail sheet. A shared Vejrforhold sheet (10-day picker, metric menu for Temperatur, Føles som, Nedbør, Vind, Luftfugtighed, Lufttryk, UV-indeks, Solstråling, Sigtbarhed; uPlot day chart of station history joined to the forecast, which is blended from the measured value over 6 h; summary and explanation in Danish) plus own sheets for Sol, Måne, Luftkvalitet, Gennemsnit, Lyn and the Nedbørsradar (2 h animation with play/pause, scrubber, steps, legend, zoom). The 10-day rows open the sheet on their day; the open sheet and day are in the URL
- `web/` 0.3.0 (phase 3 — widgets): Timeprognose (24 h strip with "Nu" from the station, sunrise/sunset markers, temperature/precipitation/wind views), 10-day forecast with temperature range bars, Vind (compass dial, Beaufort), Luftkvalitet (CAQI scale, vs. yesterday), Føles som, Luftfugtighed, Lufttryk (gauge + trend), Nedbør, UV-indeks, Solstråling, Lyn, Sigtbarhed, Sol (sun path), Måne (drawn phase), Gennemsnit (today's high vs. the 1991–2020 normal from Open-Meteo's archive, cached in the browser). Nedbørsradar: DMI radar composite (doppler, last 2 h) rendered to Web Mercator PNG frames by a new `weather-radar` systemd timer in the web LXC (`web/radar/radar_worker.py` — numpy, Pillow, pyfive; decoding and projection ported from the pydmi radar spike), served by Caddy as `/radar/*` and shown on an OpenFreeMap vector basemap (Positron by day, Dark by night; no API key — CARTO started requiring one) with MapLibre GL. Original colour weather icons. `install.sh` now generates the host's locale in the CT (silences apt-listchanges "Can't set locale")
- `web/` 0.2.0 (phase 2 — main page): animated sky (clouds, rain, snow, stars, lightning, fog, sun/twilight glow) on one canvas that pauses in background tabs and honours reduced-motion; current condition combines the forecast with what the station observes (rain gauge, lightning, wind); dawn/dusk palettes; compact sticky header on scroll; live tab title; offline/stale/forecast-error banner; PWA manifest for "Add to Home Screen"; `?sky=…&tod=…` preview parameters

## [0.8.0] - 2026-11-20

### Added
- API: `GET /api/v1/forecast` — latest forecast fetch (current + hourly + daily) for `[api] forecast_provider`/`forecast_location` (default `openmeteo`/`home`)
- API: `GET /api/v1/history?hours=&fields=` — 10-minute `history_charting` rows (max 14 days); `fields` is validated against the table's actual columns
- API: `GET /api/v1/daily?days=` — one summary row per local (`[api] timezone`) calendar day from `history_charting`: temperature high/low/avg, pressure, wind, rain total, UV/solar max, AQI/CAQI max
- These three are fetched on demand and cached for `[api] query_cache_ttl_s` (default 60 s), on their own DB connection — the 5 s poll of the combined views is unchanged
- API: `WS /api/v1/ws/current` also accepts the key as an `X-API-Key` header (for reverse proxies that inject it), in addition to `?api_key=`
- New `web/` — Danish, Apple Weather-style web frontend (Svelte 5 + TypeScript + Vite), served as a static site by Caddy in its own LXC, with Caddy proxying a whitelist of API endpoints and injecting the API key so it never reaches the browser. Phase 1: structure, data layer (WebSocket with REST fallback, forecast polling), design tokens, responsive grid, popup shell, LXC/deploy scripts. See `web/README.md`

## [0.7.0] - 2026-11-19

### Added
- New optional forecast service `weatherdatalogger/openmeteo/` (`openmeteo-datalogger`) — an alternative to Visual Crossing, or a companion: both can run for the same location. Polls the free [Open-Meteo](https://open-meteo.com) forecast API (non-commercial use, no API key) and publishes current conditions plus hourly and daily forecasts to `weatherdatalogger/forecast-openmeteo-<location>/{current,forecast_hourly,forecast_daily}` with the same field names and units as Visual Crossing, so `weatherdb-writer` stores them in the existing `forecast_*` tables under provider `openmeteo` — no schema change. The [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) integration offers `openmeteo` as a forecast provider once the first forecast is in the database
- `[openmeteo]` settings: `latitude`/`longitude`, `model` (Open-Meteo weather model, default `best_match` — e.g. `dmi_seamless` for DMI HARMONIE with ECMWF after its ~2.5-day horizon; same model ids as the Open-Meteo Home Assistant integration), `days` (default 14, max 16), `location`, `interval_min` (default 60), `api_key` (commercial plans only). Off by default (`enabled = false`); `deploy.sh` installs, enables and starts it once enabled, and the `install.sh` wizard asks for it (reusing the Visual Crossing coordinates if both are enabled)
- Fields Open-Meteo has no equivalent for (`severe_risk`, current/hourly `solar_energy`, daily `snow_depth`) are left empty; `description` is the weather code's English name ("Moderate rain") rather than a narrative sentence

## [0.6.4] - 2026-10-09

### Fixed
- `database/migrations/20261009_add_history_recorded_at_index.sql` — new `idx_history_recorded_at (recorded_at)` index on `history` (also added to `02_create_tables.sql` for fresh installs). `combined_realtime_stats` joins `history` to `stations` to resolve each role's station, so MariaDB could only use the `station_id` half of `idx_history_station_time` and walked that station's entire history in each of the view's seven subqueries — query time grew with the total size of `history` (the Davis receiver alone adds a row per RF packet, ~every 2.5 s) until it exceeded the 10 s read timeout of the [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) integration, which then logged `(2013, 'Lost connection to MySQL server during query (The read operation timed out)')` and marked all its entities unavailable. With the index the view only reads the rows inside its time windows. Applied automatically by `deploy.sh`; no view or code changes

## [0.6.3] - 2026-09-30

### Changed
- `weatherdatalogger/visualcrossing/`: requires `pyVisualCrossing>=1.1.0`. Forecast `datetime` values are now derived from the API's epoch timestamps, so they're correct UTC even when the host's timezone differs from the forecast location's (existing `forecast_hourly`/`forecast_daily` rows self-correct on the next publish via the stale-row cleanup). API requests now time out after 30 s instead of potentially hanging the poll loop, and network/timeout failures are logged as a one-line warning instead of a full traceback

## [0.6.2] - 2026-09-01

### Fixed
- `ESPHome/davis/davisnet-weatherlogger.yaml` (bumped to `0.2.5`): the 5-minute zero-out cutoff added in `0.2.4` was still too short — it kept zeroing out genuine light drizzle/rain, since tips can legitimately be 10-20+ minutes apart at low rates. The 60s tick now decays the displayed rate downward each second a tip is pending (bounded by `0.2mm / time-since-last-tip`, i.e. the highest rate still consistent with no new tip yet) instead of holding the last value frozen then hard-dropping it to `0`; only a genuine 20-minute dry spell forces a hard `0` now, as a stale-data backstop rather than the thing zeroing out real rain. Field-validated on 2026-09-01 across both drizzle and heavier rain — Rain Rate now tracks correctly at both ends

## [0.6.1] - 2026-08-17

### Fixed
- `ESPHome/davis/davisnet-weatherlogger.yaml` (bumped to `0.2.4`): Rain Rate stuck at `0` for any sustained rain at or below ~2.4 mm/h (light/moderate rain — accumulated Daily Rain was unaffected and always correct). The 60s staleness interval that blanks the displayed rate after 5 minutes without a bucket tip was reusing the same `rain_tip_seen` flag that gates the rate calculation; at ≤2.4 mm/h the gap between 0.2mm tips exceeds 5 minutes, so the flag kept getting cleared *between* tips of the same rain event and every next tip was treated as the first ever (no rate computed for it). Split into two flags — `rain_tip_seen` (idle-display blanking, still resets every 5min) and `rain_tip_ever_seen` (gates the rate math, never resets) — so a rate is now computed off however long the previous tip actually was

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
