# Open-Meteo → MQTT Forecast Datalogger

Polls the free [Open-Meteo](https://open-meteo.com) forecast API for current conditions plus hourly and daily forecasts, and republishes them to MQTT.

It is an alternative to the [Visual Crossing forecast datalogger](../visualcrossing/) — or a companion, since both can run at the same time for the same location. The payloads use the same field names and units, so [`weatherdb-writer`](../database/) stores them in the same `forecast_current`/`forecast_hourly`/`forecast_daily` tables under the provider `openmeteo`, and the [WeatherDatalogger-HA](https://github.com/briis/WeatherDatalogger-HA) integration lists it as a forecast provider when you add or reconfigure the integration.

Compared with Visual Crossing:

- **No API key, no sign-up.** The free API is for non-commercial use, up to 10,000 requests per day.
- **Choice of weather model.** For example `dmi_seamless` (DMI HARMONIE for the first ~2.5 days, then ECMWF), `ecmwf_ifs025`, `icon_seamless` or `metno_seamless`. The default `best_match` lets Open-Meteo pick. The model ids are the same as in the Open-Meteo Home Assistant integration.
- **Up to 16 days.**
- **No narrative text.** `description` is the English name of the weather code, for example "Moderate rain".

> **Installation:** Follow the [server installation guide](../../README.md#installation-debian--proxmox-lxc) first, then return here to configure the forecast datalogger.

---

## What it publishes

```
weatherdatalogger/forecast-openmeteo-<location>/current
weatherdatalogger/forecast-openmeteo-<location>/forecast_hourly
weatherdatalogger/forecast-openmeteo-<location>/forecast_daily
```

`openmeteo` is this service's `FORECAST_PROVIDER` slug (hardcoded). The payloads have the same shape as the Visual Crossing service's — see [its README](../visualcrossing/README.md#what-it-publishes) for an example and the field conventions.

### Where the values come from

All values are metric (°C, hPa, m/s, mm, km). Open-Meteo reports wind in km/h, visibility in m and snow depth in m; the service converts those to m/s, km and cm.

| Field | current | hourly | daily |
|---|---|---|---|
| `condition` | `weather_code` (+ `is_day` for clear-night) | `weather_code` + `is_day` | `weather_code` |
| `temperature` | `temperature_2m` | `temperature_2m` | `temperature_2m_max` |
| `templow` | — | — | `temperature_2m_min` |
| `temperature_high`/`temperature_low` | today's `temperature_2m_max`/`min` | — | — |
| `feels_like` | `apparent_temperature` | `apparent_temperature` | mean of `apparent_temperature_max`/`min` |
| `humidity`, `dew_point` | instant | instant | daily mean |
| `wind_speed`, `wind_gust_speed` | `wind_speed_10m`, `wind_gusts_10m` | same | daily max |
| `wind_bearing` | `wind_direction_10m` | same | `wind_direction_10m_dominant` |
| `pressure` | `pressure_msl` | `pressure_msl` | daily mean |
| `cloud_cover` | `cloud_cover` | `cloud_cover` | daily mean |
| `uv_index` | `uv_index` | `uv_index` | `uv_index_max` |
| `precipitation` | — | `precipitation` | `precipitation_sum` |
| `precipitation_probability` | — | `precipitation_probability` | `precipitation_probability_max` |
| `precipitation_cover` | — | — | `precipitation_hours` as % of 24 h |
| `visibility` | `visibility` | `visibility` | — |
| `solar_radiation` | `shortwave_radiation` (W/m²) | same | day mean, from `shortwave_radiation_sum` |
| `solar_energy` | — | — | `shortwave_radiation_sum` (MJ/m²) |
| `snow` | `snowfall` (cm) | `snowfall` | `snowfall_sum` |
| `snow_depth` | `snow_depth` (cm) | `snow_depth` | — |
| `precipitation_type` | from `weather_code` | from `weather_code` | from `weather_code` |
| `sunrise`, `sunset`, `moon_phase` | today's values | — | per day |
| `description` | weather code name | — | weather code name |
| `severe_risk` | — | — | — (Open-Meteo has no equivalent) |

`precipitation_type` uses Visual Crossing's words (`rain`, `snow`, `freezingrain`, `rain,ice` for hail) so the column means the same for both providers. `sunrise`/`sunset` are local `HH:MM:SS`, like Visual Crossing's.

A variable the chosen model doesn't provide is `null`. Hours and days past the model's horizon are left out — Open-Meteo pads every model to the requested number of days with empty values.

---

## Setup

### 1. Configure

All services share a single config file. If it doesn't exist yet:

```bash
cp /opt/weatherdatalogger/config.example.ini /opt/weatherdatalogger/config.ini
nano /opt/weatherdatalogger/config.ini
```

**Required before first start** — the service logs an error and exits cleanly (no crash loop) until these are set:

| Key | Section | What to set |
|---|---|---|
| `enabled` | `[openmeteo]` | `true` |
| `latitude`, `longitude` | `[openmeteo]` | Decimal coordinates of the forecast location |
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |

### 2. Deploy

```bash
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

`deploy.sh` installs the service and enables and starts it because `[openmeteo] enabled = true`. Or start it by hand:

```bash
systemctl enable --now openmeteo-datalogger
journalctl -u openmeteo-datalogger -f
```

You should see a `Forecast published → forecast-openmeteo-<location> (N hours, N days)` line every `interval_min` minutes.

### 3. Home Assistant

In the WeatherDatalogger-HA integration, add a new entry (or reconfigure the existing one) and pick `openmeteo` as the forecast provider. The provider appears in the list once the first forecast has been written to the database.

---

## Configuration Reference

```ini
[openmeteo]
enabled      = false       # REQUIRED — set true to enable polling
latitude     =             # REQUIRED — decimal latitude, e.g. 55.6761
longitude    =             # REQUIRED — decimal longitude, e.g. 12.5683
model        = best_match  # Open-Meteo weather model id
days         = 14          # Forecast days (today + next N), 1-16
location     = home        # Slug used in MQTT topic: forecast-openmeteo-<location>
interval_min = 60          # Poll interval in minutes
api_key      =             # Only for a commercial Open-Meteo plan
timeout_s    = 30          # HTTP request timeout
```

Shared `[mqtt]` and `[logging]` keys are the same as for the other services.

---

## Usage limits and attribution

The free API is for **non-commercial use**, within 10,000 calls per day, 5,000 per hour and 600 per minute. A request with many variables or many days counts as more than one call; this service's 14-day request counts as a handful, so the default 60-minute interval uses well under 1% of the daily limit. Most models update every 1-6 hours, so polling more often than every 15-30 minutes gains little.

An HTTP 429 (rate limit) or 400 (for example a regional model that doesn't cover the location) is logged as a warning and that poll is skipped.

Open-Meteo data is licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): show "Weather data by Open-Meteo.com" where the forecast is displayed. For commercial use, get an API key from Open-Meteo and set `api_key`; the service then uses the `customer-api.open-meteo.com` host.

---

## Why not aioopenmeteo?

[aioopenmeteo](https://github.com/briis/aioopenmeteo), the library behind the Open-Meteo Home Assistant integration, is asyncio-based. The datalogger services deliberately stay synchronous and single-file (see [AGENT.md](../../AGENT.md)), so this service makes the one HTTP request itself with `urllib` and needs nothing beyond `paho-mqtt`. The weather model ids and the weather-code → condition mapping are the same as aioopenmeteo's.

---

## Troubleshooting

Set `[logging] level = DEBUG` and restart the service to log the full request URL (without any API key). Opening that URL in a browser shows exactly what Open-Meteo returns for your location and model.
