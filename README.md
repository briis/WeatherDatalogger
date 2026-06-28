# WeatherDatalogger

A unified weather data pipeline that collects data from multiple weather station brands and publishes everything to a single MQTT broker under a common topic namespace (`weatherdatalogger/`). Downstream consumers — Home Assistant, databases, dashboards — subscribe to MQTT and are completely decoupled from the hardware.

---

## Services

| Directory | Hardware | Status |
|---|---|---|
| [`tempest/`](tempest/) | WeatherFlow Tempest (UDP → MQTT, Python service) | Active |
| [`davis/`](davis/) | Davis Vantage Vue (ESP32 + CC1101 receiver) | Planned — hardware pending |

See each subdirectory for its own README, installation instructions, and configuration reference.

---

## MQTT Topic Namespace

```
weatherdatalogger/
  tempest-<serial>/         ← WeatherFlow Tempest
    observation
    rapid_wind
    rain_start
    lightning
    device_status
    hub_status
  forecast-<location>/      ← WeatherFlow Better Forecast REST API
    current
    forecast_hourly
    forecast_daily
  davis-<id>/               ← Davis Vantage Vue (planned)
    <sensor topics>
```

---

## Development

Shared tooling lives at the repo root and applies to all services:

```bash
bash scripts/lint        # ruff format + ruff check --fix (all Python in repo)
```

Requirements: `pip install -r requirements-dev.txt`
