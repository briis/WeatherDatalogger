#!/usr/bin/env python3
"""
Visual Crossing → MQTT Forecast Datalogger.

Polls the Visual Crossing Timeline Weather API (via the `pyVisualCrossing`
wrapper) on a fixed interval and republishes current conditions plus hourly
and daily forecasts to MQTT, in the same topic shape the WeatherFlow Better
Forecast poller used to publish (now removed from tempest_datalogger.py):

    weatherdatalogger/forecast-<location>/current
    weatherdatalogger/forecast-<location>/forecast_hourly
    weatherdatalogger/forecast-<location>/forecast_daily

db_writer.py already subscribes to `forecast-+/+` and persists these to the
forecast_current/forecast_hourly/forecast_daily tables — no changes needed
there beyond the column set matching this service's payload shape.

Unlike the WeatherFlow forecast (tied to a registered Tempest station), this
is purely lat/lon-based — no station hardware required.

Usage:
    python3 visualcrossing_datalogger.py [--config config.ini]
"""

import argparse
import configparser
import json
import logging
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from pyVisualCrossing import (
    ForecastDailyData,
    ForecastData,
    ForecastHourlyData,
    VisualCrossing,
    VisualCrossingBadRequest,
    VisualCrossingException,
    VisualCrossingInternalServerError,
    VisualCrossingTooManyRequests,
    VisualCrossingUnauthorized,
)

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "visualcrossing": {
        "enabled": "false",
        "api_key": "",  # Visual Crossing API key — must be set by user
        "latitude": "",  # Forecast location — must be set by user
        "longitude": "",  # Forecast location — must be set by user
        "days": "14",  # Free tier max; today + next N days
        "language": "en",  # See pyVisualCrossing.const.SUPPORTED_LANGUAGES
        "location": "home",  # label used in MQTT topic: forecast-<location>
        "interval_min": "60",  # 24 calls/day at default — free tier is 1000/day
    },
    "mqtt": {
        "broker": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "tls": "false",
        "base_topic": "weatherdatalogger",
        "client_id": "visualcrossing-datalogger",
        "retain": "false",
        "qos": "0",
    },
    "logging": {
        "level": "INFO",
        "file": "",
    },
}

# Visual Crossing's "icons2" icon set (fixed by the pyVisualCrossing wrapper)
# mapped to Home Assistant's weather condition strings — same role as
# tempest_datalogger.py's old _WF_ICON_TO_HA, just a different source icon
# vocabulary. See https://www.visualcrossing.com/resources/documentation/weather-api/weather-condition-icons/
_VC_ICON_TO_HA: dict[str, str] = {
    "snow": "snowy",
    "snow-showers-day": "snowy",
    "snow-showers-night": "snowy",
    "thunder-rain": "lightning-rainy",
    "thunder-showers-day": "lightning-rainy",
    "thunder-showers-night": "lightning-rainy",
    "rain": "rainy",
    "showers-day": "rainy",
    "showers-night": "rainy",
    "fog": "fog",
    "wind": "windy",
    "cloudy": "cloudy",
    "partly-cloudy-day": "partlycloudy",
    "partly-cloudy-night": "partlycloudy",
    "clear-day": "sunny",
    "clear-night": "clear-night",
}


def _ha_condition(icon: str | None) -> str:
    return _VC_ICON_TO_HA.get(icon or "", "exceptional")


def _join_precip_type(precipitation_type: list[str] | None) -> str | None:
    """Flatten pyVisualCrossing's list (e.g. ["rain", "ice"]) to a joined string."""
    return ",".join(precipitation_type) if precipitation_type else None


def _kmh_to_ms(kmh: float | None) -> float | None:
    """
    Convert km/h to m/s.

    Visual Crossing's metric unit group returns wind speed/gust in km/h, but
    pyVisualCrossing's wind_speed/wind_gust_speed properties are documented
    as m/s without actually converting. Fixed here rather than in the
    wrapper to avoid a breaking change for other pyVisualCrossing consumers
    who may already depend on its current (km/h) values.
    """
    return kmh / 3.6 if kmh is not None else None


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(level_str: str, log_file: str) -> logging.Logger:
    """Configure root logger and return the named 'visualcrossing' logger."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return logging.getLogger("visualcrossing")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config(path: str) -> configparser.ConfigParser:
    """Load INI config from path, seeding DEFAULT_CONFIG first so all keys exist."""
    cfg = configparser.ConfigParser()
    for section, values in DEFAULT_CONFIG.items():
        cfg[section] = values
    if Path(path).exists():
        cfg.read(path)
    return cfg


# ---------------------------------------------------------------------------
# Payload builders — map pyVisualCrossing's data objects to the same JSON
# shape (and, deliberately, the same field names) db_writer.py's
# _FORECAST_*_FIELDS tuples expect. ForecastDailyData.wind_gust is renamed to
# wind_gust_speed here so all three payloads share one consistent key,
# despite the library itself naming it differently on daily entries.
# wind_speed/wind_gust_speed are also converted km/h → m/s via _kmh_to_ms
# (see its docstring for why that happens here and not in the wrapper).
# ---------------------------------------------------------------------------


def _build_current_payload(cc: ForecastData) -> dict:
    return {
        "condition": _ha_condition(cc.icon),
        "temperature": cc.temperature,
        "feels_like": cc.apparent_temperature,
        "humidity": cc.humidity,
        "dew_point": cc.dew_point,
        "wind_speed": _kmh_to_ms(cc.wind_speed),
        "wind_gust_speed": _kmh_to_ms(cc.wind_gust_speed),
        "wind_bearing": cc.wind_bearing,
        "pressure": cc.pressure,
        "cloud_cover": cc.cloud_cover,
        "uv_index": cc.uv_index,
        "visibility": cc.visibility,
        "solar_radiation": cc.solarradiation,
        "solar_energy": cc.solarenergy,
        "snow": cc.snow,
        "snow_depth": cc.snow_depth,
        "precipitation_type": _join_precip_type(cc.precipitation_type),
        "sunrise": cc.sunrise,
        "sunset": cc.sunset,
        "moon_phase": cc.moon_phase,
    }


def _build_hourly_payload(hourly: list[ForecastHourlyData]) -> list[dict]:
    return [
        {
            "datetime": h.datetime.isoformat(),
            "condition": _ha_condition(h.icon),
            "temperature": h.temperature,
            "feels_like": h.apparent_temperature,
            "humidity": h.humidity,
            "dew_point": h.dew_point,
            "wind_speed": _kmh_to_ms(h.wind_speed),
            "wind_gust_speed": _kmh_to_ms(h.wind_gust_speed),
            "wind_bearing": h.wind_bearing,
            "pressure": h.pressure,
            "cloud_cover": h.cloud_cover,
            "uv_index": h.uv_index,
            "precipitation": h.precipitation,
            "precipitation_probability": h.precipitation_probability,
            "visibility": h.visibility,
            "solar_radiation": h.solarradiation,
            "solar_energy": h.solarenergy,
            "severe_risk": h.severe_risk,
            "snow": h.snow,
            "snow_depth": h.snow_depth,
            "precipitation_type": _join_precip_type(h.precipitation_type),
        }
        for h in hourly
    ]


def _build_daily_payload(daily: list[ForecastDailyData]) -> list[dict]:
    return [
        {
            "datetime": d.datetime.isoformat(),
            "condition": _ha_condition(d.icon),
            "temperature": d.temperature,
            "templow": d.temp_low,
            "feels_like": d.apparent_temperature,
            "humidity": d.humidity,
            "dew_point": d.dew_point,
            "wind_speed": _kmh_to_ms(d.wind_speed),
            "wind_gust_speed": _kmh_to_ms(d.wind_gust),
            "wind_bearing": d.wind_bearing,
            "pressure": d.pressure,
            "cloud_cover": d.cloud_cover,
            "uv_index": d.uv_index,
            "precipitation": d.precipitation,
            "precipitation_probability": d.precipitation_probability,
            "precipitation_cover": d.precipitation_cover,
            "solar_radiation": d.solarradiation,
            "solar_energy": d.solarenergy,
            "severe_risk": d.severe_risk,
            "snow": d.snow,
            "snow_depth": d.snow_depth,
            "precipitation_type": _join_precip_type(d.precipitation_type),
            "sunrise": d.sunrise,
            "sunset": d.sunset,
            "moon_phase": d.moon_phase,
        }
        for d in daily
    ]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

_VC_ERRORS = (
    VisualCrossingBadRequest,
    VisualCrossingUnauthorized,
    VisualCrossingTooManyRequests,
    VisualCrossingInternalServerError,
    VisualCrossingException,
)


def _log_raw_response(vcapi: VisualCrossing, log: logging.Logger) -> None:
    """
    DEBUG-only diagnostic: dump the raw API JSON.

    Covers currentConditions plus one sample day/hour entry, to tell apart
    "Visual Crossing didn't send this field" from "pyVisualCrossing failed
    to parse a field it did send". Reaches into VisualCrossing's private
    _json_data since the library has no public accessor for the raw
    response — guarded so a future pyVisualCrossing release renaming or
    removing that attribute just skips the dump instead of breaking the
    fetch (hence the deliberately broad except below).
    """
    try:
        raw = vcapi._json_data  # noqa: SLF001
        if not raw:
            log.debug("Raw API response unavailable (empty or not yet fetched)")
            return
        current = raw.get("currentConditions", {})
        days = raw.get("days", [])
        today = days[0] if days else {}
        hours = today.get("hours", [])
        first_hour = hours[0] if hours else {}
        log.debug("Raw currentConditions: %s", json.dumps(current))
        log.debug(
            "Raw days[0] (excluding hours): %s",
            json.dumps({k: v for k, v in today.items() if k != "hours"}),
        )
        log.debug("Raw days[0].hours[0]: %s", json.dumps(first_hour))
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not introspect raw API response: %s", exc)


def fetch_forecast(vcapi: VisualCrossing, log: logging.Logger) -> ForecastData | None:
    """Fetch the current+hourly+daily forecast; None on any failure."""
    try:
        data = vcapi.fetch_data()
    except _VC_ERRORS as exc:
        log.warning("Visual Crossing API error: %s", exc)
        return None
    except Exception:
        log.exception("Unexpected error fetching Visual Crossing forecast")
        return None

    if log.isEnabledFor(logging.DEBUG):
        _log_raw_response(vcapi, log)

    return data


# ---------------------------------------------------------------------------
# MQTT helpers
# ---------------------------------------------------------------------------


def make_mqtt_client(
    cfg: configparser.ConfigParser, log: logging.Logger
) -> mqtt.Client:
    """Build and return a configured paho MQTT client (not yet connected)."""
    m = cfg["mqtt"]
    client = mqtt.Client(client_id=m["client_id"], clean_session=True)

    if m["username"]:
        client.username_pw_set(m["username"], m["password"] or None)

    if m.getboolean("tls"):
        client.tls_set()

    def on_connect(_c: mqtt.Client, _userdata: object, _flags: dict, rc: int) -> None:
        if rc == 0:
            log.info("MQTT connected to %s:%s", m["broker"], m["port"])
        else:
            log.error("MQTT connect failed, rc=%s", rc)

    def on_disconnect(_c: mqtt.Client, _userdata: object, rc: int) -> None:
        log.warning("MQTT disconnected (rc=%s), will auto-reconnect…", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    return client


def mqtt_connect(
    client: mqtt.Client, cfg: configparser.ConfigParser, log: logging.Logger
) -> None:
    """Block until the client connects to the MQTT broker, retrying on failure."""
    m = cfg["mqtt"]
    broker = m["broker"]
    port = int(m["port"])
    while True:
        try:
            client.connect(broker, port, keepalive=60)
            break
        except (OSError, ConnectionRefusedError) as exc:
            log.error(  # noqa: TRY400
                "Cannot reach MQTT broker %s:%s — %s. Retrying in 10 s…",
                broker,
                port,
                exc,
            )
            time.sleep(10)


def publish_forecast(
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    location: str,
    data: ForecastData,
    log: logging.Logger,
) -> None:
    """Publish current/hourly/daily forecast payloads for one location."""
    m = cfg["mqtt"]
    base = m["base_topic"].rstrip("/")
    retain = m.getboolean("retain")
    qos = int(m["qos"])

    subtopics = [
        ("current", _build_current_payload(data)),
        ("forecast_hourly", _build_hourly_payload(data.forecast_hourly or [])),
        ("forecast_daily", _build_daily_payload(data.forecast_daily or [])),
    ]
    for subtopic, payload in subtopics:
        topic = f"{base}/forecast-{location}/{subtopic}"
        try:
            result = client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("MQTT publish error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Publish exception for %s", topic)

    log.info("Forecast published → forecast-%s", location)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    """Connect to MQTT, then poll Visual Crossing on a fixed interval."""
    vc = cfg["visualcrossing"]
    if not vc.getboolean("enabled"):
        log.info(
            "Visual Crossing forecast disabled "
            "([visualcrossing] enabled = false) — exiting"
        )
        return

    api_key = vc["api_key"].strip()
    latitude = vc["latitude"].strip()
    longitude = vc["longitude"].strip()
    if not api_key or not latitude or not longitude:
        log.error(
            "Visual Crossing enabled but api_key/latitude/longitude not fully "
            "configured — set all three in [visualcrossing] and restart."
        )
        return

    vcapi = VisualCrossing(
        api_key,
        float(latitude),
        float(longitude),
        days=int(vc["days"]),
        language=vc["language"],
    )

    client = make_mqtt_client(cfg, log)
    mqtt_connect(client, cfg, log)
    client.loop_start()

    location = vc["location"].strip().lower().replace(" ", "-")
    interval_s = int(vc["interval_min"]) * 60

    log.info(
        "Polling Visual Crossing for (%s, %s) every %s min  →  forecast-%s",
        latitude,
        longitude,
        vc["interval_min"],
        location,
    )

    try:
        while True:
            try:
                data = fetch_forecast(vcapi, log)
                if data is not None:
                    publish_forecast(client, cfg, location, data, log)
            except Exception:
                log.exception("Unexpected error in poll loop")
            time.sleep(interval_s)
    except KeyboardInterrupt:
        log.info("Shutting down…")
    finally:
        client.loop_stop()
        client.disconnect()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the datalogger."""
    parser = argparse.ArgumentParser(
        description="Visual Crossing → MQTT forecast datalogger"
    )
    parser.add_argument(
        "--config",
        default="/opt/weatherdatalogger/config.ini",
        help="Path to config file (default: /opt/weatherdatalogger/config.ini)",
    )
    args = parser.parse_args()
    cfg = load_config(args.config)
    log_cfg = cfg["logging"]
    log = setup_logging(log_cfg["level"], log_cfg["file"])
    run(cfg, log)


if __name__ == "__main__":
    main()
