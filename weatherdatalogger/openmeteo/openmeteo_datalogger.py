#!/usr/bin/env python3
"""
Open-Meteo → MQTT Forecast Datalogger.

Polls the free Open-Meteo forecast API on a fixed interval and republishes
current conditions plus hourly and daily forecasts to MQTT:

    weatherdatalogger/forecast-openmeteo-<location>/current
    weatherdatalogger/forecast-openmeteo-<location>/forecast_hourly
    weatherdatalogger/forecast-openmeteo-<location>/forecast_daily

An alternative (or companion) to visualcrossing_datalogger.py: same topic
shape, same payload field names and units, so db_writer.py stores it in the
same forecast_current/forecast_hourly/forecast_daily tables under provider
"openmeteo", and the WeatherDatalogger-HA integration can pick it as a
forecast provider. No API key and no sign-up for non-commercial use.

The weather model is selectable (`model` in [openmeteo]), using the same
model ids as the aioopenmeteo library / ha-openmeteo integration
(best_match, dmi_seamless, ecmwf_ifs025, icon_seamless, ...).

Stdlib HTTP (urllib) rather than aioopenmeteo, which is asyncio-based — the
datalogger services deliberately stay synchronous (see AGENT.md).

Data: Open-Meteo.com, CC BY 4.0.

Usage:
    python3 openmeteo_datalogger.py [--config config.ini]
"""

import argparse
import configparser
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - zoneinfo is stdlib since 3.9
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "openmeteo": {
        "enabled": "false",
        "latitude": "",  # Forecast location — must be set by user
        "longitude": "",  # Forecast location — must be set by user
        "model": "best_match",  # Open-Meteo weather model id
        "days": "14",  # today + next N days, 1-16
        "location": "home",  # label used in MQTT topic: forecast-<provider>-<location>
        "interval_min": "60",  # 24 calls/day at default
        "api_key": "",  # only for a commercial Open-Meteo plan
        "timeout_s": "30",
    },
    "mqtt": {
        "broker": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "tls": "false",
        "base_topic": "weatherdatalogger",
        "client_id": "openmeteo-datalogger",
        "retain": "false",
        "qos": "0",
    },
    "logging": {
        "level": "INFO",
        "file": "",
    },
}

# Forecast provider slug — see visualcrossing_datalogger.py's FORECAST_PROVIDER
# for why it's hardcoded. Must not contain a hyphen: db_writer.py partitions
# the topic segment on the first "-" to split provider from location.
FORECAST_PROVIDER = "openmeteo"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Commercial plans: same path on a "customer-" host plus an `apikey` parameter.
COMMERCIAL_FORECAST_URL = "https://customer-api.open-meteo.com/v1/forecast"
MAX_DAYS = 16
USER_AGENT = (
    f"weatherdatalogger-openmeteo/{__version__} "
    "(+https://github.com/briis/WeatherDatalogger)"
)

# Requested in Open-Meteo's default metric units: °C, km/h (converted to m/s
# below), mm, snowfall cm, snow depth m (converted to cm), hPa, visibility m
# (converted to km), W/m², durations in seconds.
CURRENT_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "dew_point_2m",
    "is_day",
    "weather_code",
    "precipitation",
    "snowfall",
    "snow_depth",
    "pressure_msl",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "visibility",
    "uv_index",
    "shortwave_radiation",
)
HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "dew_point_2m",
    "is_day",
    "weather_code",
    "precipitation",
    "precipitation_probability",
    "snowfall",
    "snow_depth",
    "pressure_msl",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "visibility",
    "uv_index",
    "shortwave_radiation",
)
DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "relative_humidity_2m_mean",
    "dew_point_2m_mean",
    "pressure_msl_mean",
    "cloud_cover_mean",
    "uv_index_max",
    "precipitation_sum",
    "precipitation_hours",
    "precipitation_probability_max",
    "snowfall_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "shortwave_radiation_sum",
    "sunrise",
    "sunset",
    "moon_phase",
)

# WMO weather code → (Home Assistant condition, English description,
# Visual Crossing-style precipitation type). Conditions match aioopenmeteo's
# condition_from_wmo() so this provider and the ha-openmeteo integration
# agree; clear sky at night becomes "clear-night" in _ha_condition().
# precipitation_type uses Visual Crossing's vocabulary (rain, snow,
# freezingrain, ice) so the column means the same for both providers.
_WMO: dict[int, tuple[str, str, str | None]] = {
    0: ("sunny", "Clear sky", None),
    1: ("sunny", "Mainly clear", None),
    2: ("partlycloudy", "Partly cloudy", None),
    3: ("cloudy", "Overcast", None),
    45: ("fog", "Fog", None),
    48: ("fog", "Depositing rime fog", None),
    51: ("rainy", "Light drizzle", "rain"),
    53: ("rainy", "Moderate drizzle", "rain"),
    55: ("rainy", "Dense drizzle", "rain"),
    56: ("snowy-rainy", "Light freezing drizzle", "freezingrain"),
    57: ("snowy-rainy", "Dense freezing drizzle", "freezingrain"),
    61: ("rainy", "Slight rain", "rain"),
    63: ("rainy", "Moderate rain", "rain"),
    65: ("pouring", "Heavy rain", "rain"),
    66: ("snowy-rainy", "Light freezing rain", "freezingrain"),
    67: ("snowy-rainy", "Heavy freezing rain", "freezingrain"),
    71: ("snowy", "Slight snowfall", "snow"),
    73: ("snowy", "Moderate snowfall", "snow"),
    75: ("snowy", "Heavy snowfall", "snow"),
    77: ("snowy", "Snow grains", "snow"),
    80: ("rainy", "Slight rain showers", "rain"),
    81: ("rainy", "Moderate rain showers", "rain"),
    82: ("pouring", "Violent rain showers", "rain"),
    85: ("snowy", "Slight snow showers", "snow"),
    86: ("snowy", "Heavy snow showers", "snow"),
    95: ("lightning-rainy", "Thunderstorm", "rain"),
    96: ("hail", "Thunderstorm with slight hail", "rain,ice"),
    99: ("hail", "Thunderstorm with heavy hail", "rain,ice"),
}

_DAY = timedelta(days=1)


class OpenMeteoError(Exception):
    """Any failure fetching or reading the Open-Meteo forecast."""


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _wmo(code: Any) -> tuple[str, str, str | None] | None:
    if not isinstance(code, int | float):
        return None
    return _WMO.get(int(code))


def _ha_condition(code: Any, is_day: Any = 1) -> str | None:
    """HA weather condition for a WMO code; clear sky at night → clear-night."""
    if code is None:
        return None
    item = _wmo(code)
    if item is None:
        return "exceptional"
    condition = item[0]
    if condition == "sunny" and is_day is not None and not is_day:
        return "clear-night"
    return condition


def _description(code: Any) -> str | None:
    item = _wmo(code)
    return item[1] if item else None


def _precip_type(code: Any) -> str | None:
    item = _wmo(code)
    return item[2] if item else None


def _kmh_to_ms(kmh: Any) -> float | None:
    """Open-Meteo reports wind in km/h; this project publishes m/s everywhere."""
    return round(kmh / 3.6, 2) if isinstance(kmh, int | float) else None


def _m_to_km(metres: Any) -> int | None:
    """
    Visibility m → whole km.

    Capped at 255 — the visibility_km columns are TINYINT UNSIGNED, and some
    models report 50+ km on clear days.
    """
    if not isinstance(metres, int | float):
        return None
    return max(0, min(255, round(metres / 1000)))


def _m_to_cm(metres: Any) -> float | None:
    return round(metres * 100, 1) if isinstance(metres, int | float) else None


def _mean(a: Any, b: Any) -> float | None:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return round((a + b) / 2, 1)
    return None


def _utc_iso(epoch: Any) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def _local_hms(epoch: Any, tz: tzinfo) -> str | None:
    """
    Sunrise/sunset as local "HH:MM:SS".

    Same shape as Visual Crossing's raw sunrise/sunset strings, so the
    sunrise/sunset VARCHAR columns read the same for both providers.
    """
    if not isinstance(epoch, int | float):
        return None
    return datetime.fromtimestamp(epoch, tz).strftime("%H:%M:%S")


def _location_tz(data: dict) -> tzinfo:
    """Location's time zone (named, so DST changes inside the forecast are right)."""
    name = data.get("timezone")
    if ZoneInfo is not None and isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return timezone(timedelta(seconds=int(data.get("utc_offset_seconds") or 0)))


def _rows(section: Any) -> list[dict]:
    """Open-Meteo column arrays → one dict per time step."""
    if not isinstance(section, dict) or not isinstance(section.get("time"), list):
        return []
    times = section["time"]
    columns = {k: v for k, v in section.items() if k != "time" and isinstance(v, list)}
    rows = []
    for i, t in enumerate(times):
        row = {k: (col[i] if i < len(col) else None) for k, col in columns.items()}
        row["time"] = t
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Payload builders — same JSON shape and field names as
# visualcrossing_datalogger.py, which is what db_writer.py's
# _FORECAST_*_FIELDS tuples map to columns. Fields Open-Meteo has no
# equivalent for (severe_risk, hourly/current solar_energy, daily
# snow_depth) are sent as None.
# ---------------------------------------------------------------------------


def _today(daily: list[dict], tz: tzinfo, now: datetime) -> dict | None:
    """Daily row for the location's current local date."""
    today = now.astimezone(tz).date()
    for day in daily:
        if datetime.fromtimestamp(day["time"], tz).date() == today:
            return day
    return daily[0] if daily else None


def build_current_payload(cur: dict, today: dict | None, tz: tzinfo) -> dict:
    """Build the current payload; high/low, sun and moon come from today's daily row."""
    today = today or {}
    code = cur.get("weather_code")
    return {
        "condition": _ha_condition(code, cur.get("is_day")),
        "temperature": cur.get("temperature_2m"),
        "temperature_high": today.get("temperature_2m_max"),
        "temperature_low": today.get("temperature_2m_min"),
        "feels_like": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "dew_point": cur.get("dew_point_2m"),
        "wind_speed": _kmh_to_ms(cur.get("wind_speed_10m")),
        "wind_gust_speed": _kmh_to_ms(cur.get("wind_gusts_10m")),
        "wind_bearing": cur.get("wind_direction_10m"),
        "pressure": cur.get("pressure_msl"),
        "cloud_cover": cur.get("cloud_cover"),
        "uv_index": cur.get("uv_index"),
        "visibility": _m_to_km(cur.get("visibility")),
        "solar_radiation": cur.get("shortwave_radiation"),
        "solar_energy": None,
        "snow": cur.get("snowfall"),
        "snow_depth": _m_to_cm(cur.get("snow_depth")),
        "precipitation_type": _precip_type(code),
        "sunrise": _local_hms(today.get("sunrise"), tz),
        "sunset": _local_hms(today.get("sunset"), tz),
        "moon_phase": today.get("moon_phase"),
        "description": _description(code),
    }


def build_hourly_payload(hourly: list[dict]) -> list[dict]:
    """One entry per forecast hour."""
    return [
        {
            "datetime": _utc_iso(h["time"]),
            "condition": _ha_condition(h.get("weather_code"), h.get("is_day")),
            "temperature": h.get("temperature_2m"),
            "feels_like": h.get("apparent_temperature"),
            "humidity": h.get("relative_humidity_2m"),
            "dew_point": h.get("dew_point_2m"),
            "wind_speed": _kmh_to_ms(h.get("wind_speed_10m")),
            "wind_gust_speed": _kmh_to_ms(h.get("wind_gusts_10m")),
            "wind_bearing": h.get("wind_direction_10m"),
            "pressure": h.get("pressure_msl"),
            "cloud_cover": h.get("cloud_cover"),
            "uv_index": h.get("uv_index"),
            "precipitation": h.get("precipitation"),
            "precipitation_probability": h.get("precipitation_probability"),
            "visibility": _m_to_km(h.get("visibility")),
            "solar_radiation": h.get("shortwave_radiation"),
            "solar_energy": None,
            "severe_risk": None,
            "snow": h.get("snowfall"),
            "snow_depth": _m_to_cm(h.get("snow_depth")),
            "precipitation_type": _precip_type(h.get("weather_code")),
        }
        for h in hourly
    ]


def build_daily_payload(daily: list[dict], tz: tzinfo) -> list[dict]:
    """
    One entry per forecast day.

    `datetime` is the location's local midnight in UTC — the same convention
    Visual Crossing's day epoch uses. feels_like is the mean of the day's
    apparent max/min (Visual Crossing's daily feelslike is also a mean);
    precipitation_cover is precipitation_hours as a percentage of 24 h;
    solar_radiation is the day's mean W/m², derived from the MJ/m² sum.
    """
    payload = []
    for d in daily:
        code = d.get("weather_code")
        hours = d.get("precipitation_hours")
        energy = d.get("shortwave_radiation_sum")
        payload.append(
            {
                "datetime": _utc_iso(d["time"]),
                "condition": _ha_condition(code),
                "temperature": d.get("temperature_2m_max"),
                "templow": d.get("temperature_2m_min"),
                "feels_like": _mean(
                    d.get("apparent_temperature_max"), d.get("apparent_temperature_min")
                ),
                "humidity": d.get("relative_humidity_2m_mean"),
                "dew_point": d.get("dew_point_2m_mean"),
                "wind_speed": _kmh_to_ms(d.get("wind_speed_10m_max")),
                "wind_gust_speed": _kmh_to_ms(d.get("wind_gusts_10m_max")),
                "wind_bearing": d.get("wind_direction_10m_dominant"),
                "pressure": d.get("pressure_msl_mean"),
                "cloud_cover": d.get("cloud_cover_mean"),
                "uv_index": d.get("uv_index_max"),
                "precipitation": d.get("precipitation_sum"),
                "precipitation_probability": d.get("precipitation_probability_max"),
                "precipitation_cover": (
                    round(min(hours, 24) / 24 * 100)
                    if isinstance(hours, int | float)
                    else None
                ),
                "solar_radiation": (
                    round(energy * 1_000_000 / 86_400, 1)
                    if isinstance(energy, int | float)
                    else None
                ),
                "solar_energy": energy,
                "severe_risk": None,
                "snow": d.get("snowfall_sum"),
                "snow_depth": None,
                "precipitation_type": _precip_type(code),
                "sunrise": _local_hms(d.get("sunrise"), tz),
                "sunset": _local_hms(d.get("sunset"), tz),
                "moon_phase": d.get("moon_phase"),
                "description": _description(code),
            }
        )
    return payload


def build_payloads(data: dict, now: datetime | None = None) -> dict[str, Any]:
    """
    Turn an Open-Meteo /v1/forecast response into the three MQTT payloads.

    Rows without a temperature are dropped: Open-Meteo pads every model to
    the requested number of days, so a short-horizon model (e.g. DMI
    HARMONIE, ~2.5 days) returns only nulls past its horizon.
    """
    if not isinstance(data, dict) or not isinstance(data.get("current"), dict):
        msg = "Unexpected Open-Meteo response (no current conditions)"
        raise OpenMeteoError(msg)
    tz = _location_tz(data)
    hourly = [
        h for h in _rows(data.get("hourly")) if h.get("temperature_2m") is not None
    ]
    daily = [
        d for d in _rows(data.get("daily")) if d.get("temperature_2m_max") is not None
    ]
    today = _today(daily, tz, now or datetime.now(UTC))
    return {
        "current": build_current_payload(data["current"], today, tz),
        "forecast_hourly": build_hourly_payload(hourly),
        "forecast_daily": build_daily_payload(daily, tz),
    }


# ---------------------------------------------------------------------------
# Logging / config
# ---------------------------------------------------------------------------


def setup_logging(level_str: str, log_file: str) -> logging.Logger:
    """Configure root logger and return the named 'openmeteo' logger."""
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
    return logging.getLogger("openmeteo")


def load_config(path: str) -> configparser.ConfigParser:
    """Load INI config from path, seeding DEFAULT_CONFIG first so all keys exist."""
    cfg = configparser.ConfigParser()
    for section, values in DEFAULT_CONFIG.items():
        cfg[section] = values
    if Path(path).exists():
        cfg.read(path)
    return cfg


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def build_request_url(
    latitude: float,
    longitude: float,
    model: str,
    days: int,
    api_key: str = "",
) -> str:
    """Full /v1/forecast URL (one request covers current, hourly and daily)."""
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "models": model,
        "forecast_days": str(days),
        "timezone": "auto",
        "timeformat": "unixtime",
        "current": ",".join(CURRENT_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
        "daily": ",".join(DAILY_VARIABLES),
    }
    base = FORECAST_URL
    if api_key:
        params["apikey"] = api_key
        base = COMMERCIAL_FORECAST_URL
    return f"{base}?{urllib.parse.urlencode(params, safe=',')}"


def _error_reason(exc: urllib.error.HTTPError) -> str:
    """Open-Meteo puts the explanation in a JSON {"reason": ...} body."""
    try:
        body = exc.read().decode("utf-8", "replace")
    except OSError:
        return str(exc)
    try:
        reason = json.loads(body).get("reason")
    except (ValueError, AttributeError):
        reason = None
    return str(reason or body[:300] or exc)


def fetch_forecast(url: str, timeout_s: float) -> dict:
    """GET the forecast; raises OpenMeteoError on any HTTP/network/JSON problem."""
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        reason = _error_reason(exc)
        if exc.code == 429:  # noqa: PLR2004
            msg = f"Rate limited by Open-Meteo (HTTP 429): {reason}"
        else:
            msg = f"HTTP {exc.code}: {reason}"
        raise OpenMeteoError(msg) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        msg = f"Cannot reach Open-Meteo: {exc}"
        raise OpenMeteoError(msg) from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        msg = f"Invalid JSON from Open-Meteo: {exc}"
        raise OpenMeteoError(msg) from exc


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
    payloads: dict[str, Any],
    log: logging.Logger,
) -> None:
    """Publish current/hourly/daily forecast payloads for one location."""
    m = cfg["mqtt"]
    base = m["base_topic"].rstrip("/")
    retain = m.getboolean("retain")
    qos = int(m["qos"])

    for subtopic in ("current", "forecast_hourly", "forecast_daily"):
        topic = f"{base}/forecast-{FORECAST_PROVIDER}-{location}/{subtopic}"
        try:
            result = client.publish(
                topic, json.dumps(payloads[subtopic]), qos=qos, retain=retain
            )
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("MQTT publish error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Publish exception for %s", topic)

    log.info(
        "Forecast published → forecast-%s-%s (%d hours, %d days)",
        FORECAST_PROVIDER,
        location,
        len(payloads["forecast_hourly"]),
        len(payloads["forecast_daily"]),
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    """Connect to MQTT, then poll Open-Meteo on a fixed interval."""
    om = cfg["openmeteo"]
    if not om.getboolean("enabled"):
        log.info("Open-Meteo forecast disabled ([openmeteo] enabled = false) — exiting")
        return

    try:
        latitude = float(om["latitude"])
        longitude = float(om["longitude"])
    except ValueError:
        log.error(  # noqa: TRY400
            "Open-Meteo enabled but latitude/longitude not set to decimal "
            "degrees — set both in [openmeteo] and restart."
        )
        return

    days = max(1, min(MAX_DAYS, int(om["days"])))
    model = om["model"].strip() or "best_match"
    url = build_request_url(latitude, longitude, model, days, om["api_key"].strip())
    timeout_s = float(om["timeout_s"])
    log.debug(
        "Request URL (api key omitted): %s",
        build_request_url(latitude, longitude, model, days),
    )

    client = make_mqtt_client(cfg, log)
    mqtt_connect(client, cfg, log)
    client.loop_start()

    location = om["location"].strip().lower().replace(" ", "-")
    interval_s = int(om["interval_min"]) * 60

    log.info(
        "Polling Open-Meteo (%s) for (%s, %s), %d days, every %s min → forecast-%s-%s",
        model,
        latitude,
        longitude,
        days,
        om["interval_min"],
        FORECAST_PROVIDER,
        location,
    )

    try:
        while True:
            try:
                payloads = build_payloads(fetch_forecast(url, timeout_s))
                publish_forecast(client, cfg, location, payloads, log)
            except OpenMeteoError as exc:
                log.warning("Open-Meteo: %s", exc)
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
        description="Open-Meteo → MQTT forecast datalogger"
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
