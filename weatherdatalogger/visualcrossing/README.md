# Visual Crossing → MQTT Forecast Datalogger

Polls the [Visual Crossing](https://www.visualcrossing.com/) Timeline Weather API — via the [`pyVisualCrossing`](https://github.com/briis/pyVisualCrossing) wrapper — for current conditions plus hourly and daily forecasts, and republishes them to MQTT.

This replaces the WeatherFlow Better Forecast poller that used to live in `tempest_datalogger.py`. Unlike that one, this service is purely **latitude/longitude-based** — it has no dependency on a registered Tempest station, WeatherFlow account, or any physical hardware at all.

> **Installation:** Follow the [server installation guide](../../README.md#installation) first, then return here to configure the forecast datalogger.

---

## What it publishes

Same topic shape the WeatherFlow forecast used to publish, so [`weatherdb-writer`](../database/) needs no changes beyond the column set it already expects:

```
weatherdatalogger/forecast-<location>/current
weatherdatalogger/forecast-<location>/forecast_hourly
weatherdatalogger/forecast-<location>/forecast_daily
```

| Subtopic | Payload | Content |
|---|---|---|
| `current` | JSON object | Current conditions |
| `forecast_hourly` | JSON array | One entry per forecast hour |
| `forecast_daily` | JSON array | One entry per forecast day |

### Example `current` payload

```json
{
  "condition": "partlycloudy",
  "temperature": 18.2,
  "temperature_high": 21.0,
  "temperature_low": 11.4,
  "feels_like": 19.5,
  "humidity": 72,
  "dew_point": 12.9,
  "wind_speed": 3.1,
  "wind_gust_speed": 6.5,
  "wind_bearing": 247,
  "pressure": 1013.2,
  "cloud_cover": 40,
  "uv_index": 3,
  "visibility": 15,
  "solar_radiation": 250.0,
  "solar_energy": 21.6,
  "snow": 0.0,
  "snow_depth": 0.0,
  "precipitation_type": "rain",
  "sunrise": "04:52:00",
  "sunset": "21:58:00",
  "moon_phase": 0.42
}
```

`forecast_hourly`/`forecast_daily` entries carry most of the same field names, plus `datetime`, `precipitation`, `precipitation_probability`, and `severe_risk`. A few fields are only present on some of the three payloads, reflecting what Visual Crossing itself reports at each granularity:

| Field | current | hourly | daily |
|---|---|---|---|
| `visibility` | ✓ | ✓ | — |
| `solar_radiation`, `solar_energy`, `snow`, `snow_depth`, `precipitation_type` | ✓ | ✓ | ✓ |
| `severe_risk` | — | ✓ | ✓ |
| `sunrise`, `sunset`, `moon_phase` | ✓ | — | ✓ |
| `precipitation_cover` | — | — | ✓ |

Daily entries additionally have `templow` (the day's low, alongside `temperature` for the high). `current` additionally has `temperature_high`/`temperature_low` — Visual Crossing's `currentConditions` has no high/low of its own, so this service fills those two from `forecast_daily[0]` (today's entry) before publishing. `precipitation_type` comes back from `pyVisualCrossing` as a list (e.g. `["rain", "ice"]`, or `null`); this service flattens it to a single comma-joined string (`"rain,ice"`) before publishing, so downstream consumers don't need to parse a nested array out of the MQTT payload.

### Field conventions

Field names intentionally match Home Assistant's own weather-entity attribute names (`condition`, `temperature`, `wind_bearing`, ...) rather than this project's usual unit-suffixed convention (`temperature_c`, `wind_bearing_deg`) — same as the WeatherFlow forecast payload before it. `weatherdb-writer` maps them to proper unit-suffixed DB columns (`temperature_c`, `wind_speed_ms`, ...) on the way into MariaDB; see [`database/README.md`](../database/README.md#forecast_current-forecast_hourly-forecast_daily). One exception: the MQTT payload's `condition` key maps to the DB column `weather_condition`, not `condition` — `CONDITION` is a reserved word in MariaDB.

All values are metric (°C, hPa/mb, m/s), matching the rest of this project. Most unit conversion is done by `pyVisualCrossing` itself, with one exception: Visual Crossing's `unitGroup=metric` returns wind speed and gust in **km/h**, but `pyVisualCrossing`'s `wind_speed`/`wind_gust_speed` properties are documented as m/s without actually converting. Rather than patch the wrapper (which could break other consumers relying on its current km/h values), this service converts `wind_speed`/`wind_gust_speed` from km/h to m/s itself, via `_kmh_to_ms()` in `visualcrossing_datalogger.py`, before publishing.

`condition` is Home Assistant's mapped weather condition (`sunny`, `partlycloudy`, `rainy`, ...), derived from Visual Crossing's `icons2` icon set — not the API's own verbose native-language condition text, which isn't republished. See `_VC_ICON_TO_HA` in `visualcrossing_datalogger.py` for the full mapping.

`wind_gust_speed` is normalized to one consistent name across all three payloads — `pyVisualCrossing`'s own daily forecast objects expose it as `wind_gust` (vs. `wind_gust_speed` on current/hourly objects); this service renames it on the way out so downstream consumers don't need to special-case daily entries.

---

## Setup

### 1. Get a Visual Crossing API key

Sign up for the **free tier** (1,000 calls/day) at [visualcrossing.com/weather-data-editions](https://www.visualcrossing.com/weather-data-editions) and generate an API key.

### 2. Configure

All services share a single config file. If it doesn't exist yet:

```bash
cp /opt/weatherdatalogger/config.example.ini /opt/weatherdatalogger/config.ini
nano /opt/weatherdatalogger/config.ini
```

**Required before first start** — the service logs an error and idles (not crash-loops) until these are set:

| Key | Section | What to set |
|---|---|---|
| `enabled` | `[visualcrossing]` | `true` |
| `api_key` | `[visualcrossing]` | Your Visual Crossing API key |
| `latitude`, `longitude` | `[visualcrossing]` | Decimal coordinates of the forecast location |
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |

Everything else has sensible defaults.

### 3. Enable and start

```bash
systemctl enable --now visualcrossing-datalogger
journalctl -u visualcrossing-datalogger -f
```

You should see a `Forecast published → forecast-<location>` line every `interval_min` minutes.

---

## Configuration Reference

Settings live in the shared `/opt/weatherdatalogger/config.ini`. Visual Crossing-specific keys:

```ini
[visualcrossing]
enabled      = false   # REQUIRED — set true to enable polling
api_key      =         # REQUIRED — Visual Crossing API key
latitude     =         # REQUIRED — decimal latitude, e.g. 55.6761
longitude    =         # REQUIRED — decimal longitude, e.g. 12.5683
days         = 14      # Forecast days to request (today + next N); free tier max
language     = en      # Native condition text language — see pyVisualCrossing.const.SUPPORTED_LANGUAGES (includes da)
location     = home    # Slug used in MQTT topic: forecast-<location>
interval_min = 60      # Poll interval in minutes — 60 min = 24 calls/day
```

Shared keys used by this service:

```ini
[mqtt]
broker     = localhost     # REQUIRED — MQTT broker hostname or IP
port       = 1883
username   =
password   =
tls        = false
base_topic = weatherdatalogger
retain     = true          # recommended — gives db_writer/HA a value immediately on (re)connect
qos        = 0

[logging]
level = INFO
file  =
```

---

## Managing your free-tier quota

The free tier allows 1,000 calls/day, and this service makes exactly one call per poll (`interval_min`). At the default 60-minute interval that's 24 calls/day — comfortable headroom for occasional manual testing too. Lowering `interval_min` below ~15 minutes starts eating meaningfully into the daily quota; a `429 TOO_MANY_REQUESTS` from the API is logged as a warning (`Visual Crossing API error: ...`) and simply skips that poll, it does not crash the service.

---

## Relationship to `pyVisualCrossing`

This service is a thin wrapper around [`pyVisualCrossing`](https://github.com/briis/pyVisualCrossing) — it calls `VisualCrossing(...).fetch_data()` on a timer and reshapes the returned `ForecastData`/`ForecastHourlyData`/`ForecastDailyData` objects into the MQTT JSON payloads documented above. The library's own `fetch_data()` is synchronous (blocking HTTP via `urllib`); `async_fetch_data()` also exists but isn't used here since this service already runs its own poll loop in a dedicated process.

`requirements.txt` pins `pyVisualCrossing>=1.0.2` — that's the version where the package started declaring `aiohttp` as its own dependency (earlier versions imported it unconditionally in `api.py` without declaring it, leaving `pip install` with a broken import unless you added `aiohttp` yourself) and where the full field set this service reads (`snow`, `precipitation_type`, `solar_energy`, `severe_risk`, `sunrise`/`sunset`, `moon_phase`, plus `solar_radiation`/`visibility` on hourly entries) became available — earlier versions silently returned `None` for most of these on hourly/daily objects, even though the underlying API response already included them.

---

## Troubleshooting

### Some fields are always `null` (e.g. `feels_like`, `cloud_cover`, `uv_index`, `wind_gust_speed`, `snow`, `sunrise`)

This is usually Visual Crossing's own API response for that location not including the field — not a bug in this service or in `pyVisualCrossing`'s parsing. To tell the two apart, set `[logging] level = DEBUG` in `config.ini`, restart the service, and check the next fetch:

```bash
journalctl -u visualcrossing-datalogger -f
```

Look for three `DEBUG` lines: `Raw currentConditions: ...`, `Raw days[0] (excluding hours): ...`, and `Raw days[0].hours[0]: ...` — these dump the actual JSON Visual Crossing returned, before any of this service's parsing. If a field is missing or `null` there too, it's a Visual Crossing data-availability question for that location (check with their support, or whether your account/plan restricts certain elements), not something fixable here. If a field *is* present there but still comes through as `null` in the published MQTT payload or the database, that points to a bug in `pyVisualCrossing` itself (reading the wrong JSON key) — worth reporting upstream.

Remember to set `[logging] level` back to `INFO` afterward — `DEBUG` logs the full raw API response on every poll.
