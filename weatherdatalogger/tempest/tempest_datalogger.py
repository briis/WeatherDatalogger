#!/usr/bin/env python3
"""
WeatherFlow Tempest UDP → MQTT Datalogger.

Listens for UDP broadcasts from a WeatherFlow Tempest hub on port 50222
and publishes parsed observations to MQTT under the topic:

    weatherdatalogger/tempest-<serial_number>/...

Subtopics published:
  .../observation   — full Tempest obs (obs_st) as a flat JSON object
  .../rapid_wind    — rapid wind updates
  .../rain_start    — precipitation start events
  .../lightning     — lightning strike events
  .../device_status — device health
  .../hub_status    — hub health

Usage:
    python3 tempest_datalogger.py [--config config.ini]

Configuration is read from config.ini (see below for defaults).
"""

import argparse
import configparser
import contextlib
import json
import logging
import math
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "udp": {
        "listen_address": "0.0.0.0",  # noqa: S104
        "listen_port": "50222",
    },
    "mqtt": {
        "broker": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "tls": "false",
        "base_topic": "weatherdatalogger",
        "client_id": "tempest-datalogger",
        "retain": "false",
        "qos": "0",
    },
    "logging": {
        "level": "INFO",
        "file": "",  # empty = stderr only
    },
    "homeassistant": {
        "discovery": "false",
        "discovery_prefix": "homeassistant",
    },
    "station": {
        "elevation_m": "0",
        "height_above_ground_m": "0",
        "data_dir": "",  # empty = same directory as the config file
    },
    "forecast": {
        "enabled": "false",
        "station_id": "",  # WeatherFlow station ID — must be set by user
        "api_key": "",  # WeatherFlow API key — must be set by user
        "location": "home",  # label used in MQTT topic: forecast-<location>
        "interval_min": "30",
        "forecast_hours": "48",
        "units_temp": "c",
        "units_wind": "mps",
        "units_pressure": "hpa",
        "units_precip": "mm",
        "units_distance": "km",
    },
}

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(level_str: str, log_file: str) -> logging.Logger:
    """Configure root logger and return the named 'tempest' logger."""
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
    return logging.getLogger("tempest")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config(path: str) -> configparser.ConfigParser:
    """Load INI config from path, seeding DEFAULT_CONFIG first so all keys exist."""
    cfg = configparser.ConfigParser()
    # seed defaults
    for section, values in DEFAULT_CONFIG.items():
        cfg[section] = values
    if Path(path).exists():
        cfg.read(path)
    return cfg


# ---------------------------------------------------------------------------
# Message parsers
# ---------------------------------------------------------------------------


def parse_obs_st(msg: dict) -> dict | None:
    """Parse a Tempest observation (obs_st) into a flat dict."""
    try:
        obs = msg["obs"][0]
        return {
            "timestamp": obs[0],
            "wind_lull_ms": obs[1],
            "wind_avg_ms": obs[2],
            "wind_gust_ms": obs[3],
            "wind_direction_deg": obs[4],
            "wind_sample_interval_s": obs[5],
            "station_pressure_mb": obs[6],
            "air_temperature_c": obs[7],
            "relative_humidity_pct": obs[8],
            "illuminance_lux": obs[9],
            "uv_index": obs[10],
            "solar_radiation_wm2": obs[11],
            "rain_accumulation_mm": obs[12],
            "precipitation_type": obs[13],  # 0=none,1=rain,2=hail,3=rain+hail
            "lightning_avg_dist_km": obs[14],
            "lightning_strike_count": obs[15],
            "battery_volts": obs[16],
            "reporting_interval_min": obs[17],
            "serial_number": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
            "firmware_revision": msg.get("firmware_revision"),
        }
    except (KeyError, IndexError, TypeError):
        return None


def parse_rapid_wind(msg: dict) -> dict | None:
    """Parse a rapid_wind message into a flat dict."""
    try:
        ob = msg["ob"]
        return {
            "timestamp": ob[0],
            "wind_speed_ms": ob[1],
            "wind_direction_deg": ob[2],
            "serial_number": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
        }
    except (KeyError, IndexError, TypeError):
        return None


def parse_evt_precip(msg: dict) -> dict | None:
    """Parse a precipitation-start event into a flat dict."""
    try:
        return {
            "timestamp": msg["evt"][0],
            "serial_number": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
        }
    except (KeyError, IndexError, TypeError):
        return None


def parse_evt_strike(msg: dict) -> dict | None:
    """Parse a lightning-strike event into a flat dict."""
    try:
        evt = msg["evt"]
        return {
            "timestamp": evt[0],
            "distance_km": evt[1],
            "energy": evt[2],
            "serial_number": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
        }
    except (KeyError, IndexError, TypeError):
        return None


def parse_device_status(msg: dict) -> dict:
    """Parse a device_status message into a flat dict."""
    return {
        "timestamp": msg.get("timestamp"),
        "uptime_s": msg.get("uptime"),
        "voltage": msg.get("voltage"),
        "firmware_revision": msg.get("firmware_revision"),
        "rssi": msg.get("rssi"),
        "hub_rssi": msg.get("hub_rssi"),
        "sensor_status": msg.get("sensor_status"),
        "debug": msg.get("debug"),
        "serial_number": msg.get("serial_number"),
        "hub_sn": msg.get("hub_sn"),
    }


def parse_hub_status(msg: dict) -> dict:
    """Parse a hub_status message into a flat dict."""
    radio = msg.get("radio_stats", [])
    return {
        "timestamp": msg.get("timestamp"),
        "firmware_revision": msg.get("firmware_revision"),
        "uptime_s": msg.get("uptime"),
        "rssi": msg.get("rssi"),
        "reset_flags": msg.get("reset_flags"),
        "seq": msg.get("seq"),
        "radio_version": radio[0] if len(radio) > 0 else None,
        "radio_reboot_count": radio[1] if len(radio) > 1 else None,
        "radio_status": radio[3] if len(radio) > 3 else None,  # noqa: PLR2004
        "serial_number": msg.get("serial_number"),
    }


# ---------------------------------------------------------------------------
# Derived metrics  (source: apidocs.tempestwx.com/reference/derived-metrics)
# ---------------------------------------------------------------------------

_R_DRY_AIR = 287.058  # J/(kg·K)
_SLP_P0 = 1013.25  # mb — standard sea level pressure
_SLP_RD = 287.05  # J/(kg·K) — gas constant for dry air
_SLP_GAMMA_S = 0.0065  # K/m — standard lapse rate
_SLP_G = 9.80665  # m/s²
_SLP_T0 = 288.15  # K — standard sea level temperature
_SLP_EXPONENT = _SLP_G / (_SLP_RD * _SLP_GAMMA_S)

_HI_TEMP_MIN_F = 80.0  # heat index valid above this (°F)
_HI_RH_MIN = 40.0  # heat index valid above this (%)
_WC_TEMP_MAX_F = 50.0  # wind chill valid below this (°F)
_WC_WIND_MIN_MPH = 3.0  # wind chill valid above this (mph)
_PRESSURE_TREND_MB = 1.0  # threshold for Rising/Falling label
_PRESSURE_TREND_TOL_S = 600  # ±10 min tolerance when finding 3h-old reading


def _c_to_f(t: float) -> float:
    return t * 9.0 / 5.0 + 32.0


def _f_to_c(t: float) -> float:
    return (t - 32.0) * 5.0 / 9.0


def _ms_to_mph(v: float) -> float:
    return v * 2.23694


def _dew_point_c(t_c: float, rh: float) -> float | None:
    if rh <= 0:
        return None
    gamma = math.log(rh / 100.0) + 17.625 * t_c / (243.04 + t_c)
    return round(243.04 * gamma / (17.625 - gamma), 1)


def _vapor_pressure_mb(t_c: float, rh: float) -> float:
    return round((rh / 100.0) * 6.112 * math.exp(17.67 * t_c / (t_c + 243.5)), 2)


def _wet_bulb_c(t_c: float, rh: float, p_mb: float) -> float:
    """Solve for wet bulb temperature using iterative bisection."""
    pv = (rh / 100.0) * 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))

    def residual(twb: float) -> float:
        pv_wb = 6.112 * math.exp(17.67 * twb / (twb + 243.5))
        return pv_wb - p_mb * (t_c - twb) * 0.00066 * (1.0 + 0.00115 * twb) - pv

    lo, hi = -50.0, t_c
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if residual(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 1)


def _heat_index_c(t_c: float, rh: float) -> float | None:
    t_f = _c_to_f(t_c)
    if t_f < _HI_TEMP_MIN_F or rh < _HI_RH_MIN:
        return None
    hi_f = (
        -42.379
        + 2.04901523 * t_f
        + 10.14333127 * rh
        - 0.22475541 * t_f * rh
        - 6.83783e-3 * t_f**2
        - 5.481717e-2 * rh**2
        + 1.22874e-3 * t_f**2 * rh
        + 8.5282e-4 * t_f * rh**2
        - 1.99e-6 * t_f**2 * rh**2
    )
    return round(_f_to_c(hi_f), 1)


def _wind_chill_c(t_c: float, wind_ms: float) -> float | None:
    t_f = _c_to_f(t_c)
    v_mph = _ms_to_mph(wind_ms)
    if t_f > _WC_TEMP_MAX_F or v_mph <= _WC_WIND_MIN_MPH:
        return None
    wc_f = 35.74 + 0.6215 * t_f - 35.75 * v_mph**0.16 + 0.4275 * t_f * v_mph**0.16
    return round(_f_to_c(wc_f), 1)


def _feels_like_c(t_c: float, rh: float, wind_ms: float) -> float:
    t_f = _c_to_f(t_c)
    v_mph = _ms_to_mph(wind_ms)
    if t_f >= _HI_TEMP_MIN_F and rh >= _HI_RH_MIN:
        hi = _heat_index_c(t_c, rh)
        if hi is not None:
            return hi
    if t_f <= _WC_TEMP_MAX_F and v_mph > _WC_WIND_MIN_MPH:
        wc = _wind_chill_c(t_c, wind_ms)
        if wc is not None:
            return wc
    return round(t_c, 1)


def _air_density(p_mb: float, t_c: float) -> float:
    return round(p_mb * 100.0 / (_R_DRY_AIR * (t_c + 273.15)), 3)


def _sea_level_pressure_mb(p_sta: float, h_el: float, h_ag: float) -> float:
    inner = (
        (_SLP_P0 / p_sta) ** (_SLP_RD * _SLP_GAMMA_S / _SLP_G)
        * _SLP_GAMMA_S
        * (h_el + h_ag)
        / _SLP_T0
    )
    return round(p_sta * (1.0 + inner) ** _SLP_EXPONENT, 1)


# Pressure history (persisted across restarts for 3-hour trend)

_PRESSURE_KEEP_S = 24 * 3600

_pressure_history: list[dict] = []
_pressure_file: list[Path | None] = [None]  # mutable cell avoids `global`


def _pressure_data_path(cfg: configparser.ConfigParser, config_path: str) -> Path:
    data_dir = cfg["station"].get("data_dir", "").strip()
    if data_dir:
        return Path(data_dir) / "tempest_pressure.json"
    return Path(config_path).resolve().parent / "tempest_pressure.json"


def _load_pressure(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        cutoff = int(time.time()) - _PRESSURE_KEEP_S
        return [e for e in data.get("history", []) if e.get("ts", 0) >= cutoff]
    except Exception:  # noqa: BLE001
        return []


def _save_pressure() -> None:
    path = _pressure_file[0]
    if path is None:
        return
    with contextlib.suppress(Exception):
        path.write_text(json.dumps({"history": _pressure_history}))


def init_pressure(
    cfg: configparser.ConfigParser, config_path: str, log: logging.Logger
) -> None:
    """Load persisted pressure history from disk and configure the storage path."""
    path = _pressure_data_path(cfg, config_path)
    _pressure_file[0] = path
    history = _load_pressure(path)
    _pressure_history.clear()
    _pressure_history.extend(history)
    log.info("Pressure history: %d reading(s) loaded from %s", len(history), path)


def record_pressure(ts: int, stn_mb: float, slp_mb: float) -> None:
    """Record a station + sea-level pressure pair and persist the history."""
    _pressure_history.append({"ts": ts, "stn": stn_mb, "slp": slp_mb})
    cutoff = ts - _PRESSURE_KEEP_S
    while _pressure_history and _pressure_history[0]["ts"] < cutoff:
        _pressure_history.pop(0)
    _save_pressure()


def _pressure_trend(now_ts: int, field: str) -> tuple[float | None, str | None]:
    target_ts = now_ts - 3 * 3600
    best_diff = float("inf")
    p_3h: float | None = None
    for entry in _pressure_history:
        diff = abs(entry["ts"] - target_ts)
        if diff < best_diff:
            best_diff = diff
            p_3h = entry.get(field)
    if p_3h is None or best_diff > _PRESSURE_TREND_TOL_S:
        return None, None
    current = _pressure_history[-1].get(field) if _pressure_history else None
    if current is None:
        return None, None
    delta = round(current - p_3h, 1)
    if delta <= -_PRESSURE_TREND_MB:
        return delta, "Falling"
    if delta >= _PRESSURE_TREND_MB:
        return delta, "Rising"
    return delta, "Steady"


# Lightning history (persisted across restarts)

_LIGHTNING_WINDOW_S = 3 * 3600  # 3-hour summary window
_LIGHTNING_KEEP_S = 24 * 3600  # retain events for up to 24 hours

_lightning_events: list[dict] = []
_lightning_file: list[Path | None] = [None]  # mutable cell avoids `global`


def _lightning_data_path(cfg: configparser.ConfigParser, config_path: str) -> Path:
    data_dir = cfg["station"].get("data_dir", "").strip()
    if data_dir:
        return Path(data_dir) / "tempest_lightning.json"
    return Path(config_path).resolve().parent / "tempest_lightning.json"


def _load_lightning(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        cutoff = int(time.time()) - _LIGHTNING_KEEP_S
        return [e for e in data.get("events", []) if e.get("ts", 0) >= cutoff]
    except Exception:  # noqa: BLE001
        return []


def _save_lightning() -> None:
    path = _lightning_file[0]
    if path is None:
        return
    with contextlib.suppress(Exception):
        path.write_text(json.dumps({"events": _lightning_events}))


def init_lightning(
    cfg: configparser.ConfigParser, config_path: str, log: logging.Logger
) -> None:
    """Load persisted lightning events from disk and configure the storage path."""
    path = _lightning_data_path(cfg, config_path)
    _lightning_file[0] = path
    events = _load_lightning(path)
    _lightning_events.clear()
    _lightning_events.extend(events)
    log.info("Lightning history: %d event(s) loaded from %s", len(events), path)


def record_lightning_strike(ts: int, dist: float | None) -> None:
    """Append a strike event to the in-memory list and persist to disk."""
    _lightning_events.append({"ts": ts, "dist": dist})
    cutoff = ts - _LIGHTNING_KEEP_S
    while _lightning_events and _lightning_events[0]["ts"] < cutoff:
        _lightning_events.pop(0)
    _save_lightning()


def lightning_summary(now_ts: int) -> dict:
    """Return 3h lightning summary fields for inclusion in the obs_st payload."""
    cutoff = now_ts - _LIGHTNING_WINDOW_S
    recent = [e for e in _lightning_events if e["ts"] >= cutoff]
    last_ts_val = max((e["ts"] for e in _lightning_events), default=None)
    last_ts = (
        datetime.fromtimestamp(last_ts_val, tz=UTC).isoformat()
        if last_ts_val is not None
        else None
    )
    dists = [e["dist"] for e in recent if e.get("dist") is not None]
    return {
        "lightning_last_detected": last_ts,
        "lightning_count_3h": len(recent),
        "lightning_min_dist_3h_km": min(dists) if dists else None,
        "lightning_max_dist_3h_km": max(dists) if dists else None,
    }


def compute_obs_derived(obs: dict, cfg: configparser.ConfigParser) -> dict:
    """Compute all Tempest derived metrics from a parsed obs_st payload."""
    t_c = obs.get("air_temperature_c")
    rh = obs.get("relative_humidity_pct")
    p_mb = obs.get("station_pressure_mb")
    wind_ms = obs.get("wind_avg_ms")
    rain_mm = obs.get("rain_accumulation_mm")
    ts = obs.get("timestamp")

    if None in (t_c, rh, p_mb, wind_ms):
        return {}

    wb = _wet_bulb_c(t_c, rh, p_mb)
    t_c_r = round(t_c, 1)
    hi = _heat_index_c(t_c, rh)
    wc = _wind_chill_c(t_c, wind_ms)
    derived: dict = {
        "vapor_pressure_mb": _vapor_pressure_mb(t_c, rh),
        "dew_point_c": _dew_point_c(t_c, rh),
        "wet_bulb_c": wb,
        "delta_t_c": round(t_c - wb, 1),
        "heat_index_c": hi if hi is not None else t_c_r,
        "wind_chill_c": wc if wc is not None else t_c_r,
        "feels_like_c": _feels_like_c(t_c, rh, wind_ms),
        "air_density_kgm3": _air_density(p_mb, t_c),
        "rain_rate_mmh": round(rain_mm * 60.0, 2) if rain_mm is not None else None,
    }

    st = cfg["station"]
    slp = _sea_level_pressure_mb(
        p_mb, float(st["elevation_m"]), float(st["height_above_ground_m"])
    )
    derived["sea_level_pressure_mb"] = slp

    now_ts = int(ts) if ts is not None else int(time.time())
    record_pressure(now_ts, p_mb, slp)

    stn_delta, stn_label = _pressure_trend(now_ts, "stn")
    derived["pressure_trend_mb"] = stn_delta
    derived["pressure_trend"] = stn_label

    slp_delta, slp_label = _pressure_trend(now_ts, "slp")
    derived["sea_level_pressure_trend_mb"] = slp_delta
    derived["sea_level_pressure_trend"] = slp_label

    derived.update(lightning_summary(now_ts))

    return derived


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


def publish(
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    topic: str,
    payload: dict,
    log: logging.Logger,
) -> None:
    """Serialise payload as JSON and publish it; log but do not raise on error."""
    m = cfg["mqtt"]
    retain = m.getboolean("retain")
    qos = int(m["qos"])
    try:
        result = client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("MQTT publish error rc=%s topic=%s", result.rc, topic)
        else:
            log.debug("Published → %s", topic)
    except Exception:
        log.exception("Publish exception")


# ---------------------------------------------------------------------------
# Home Assistant MQTT Discovery
# ---------------------------------------------------------------------------

# Each entry: (field, friendly_name, unit_of_measurement, device_class, state_class)
_ST_OBS_SENSORS = [
    ("air_temperature_c", "Temperature", "°C", "temperature", "measurement"),
    ("relative_humidity_pct", "Humidity", "%", "humidity", "measurement"),
    ("station_pressure_mb", "Pressure", "hPa", "atmospheric_pressure", "measurement"),
    ("wind_avg_ms", "Wind Speed", "m/s", "wind_speed", "measurement"),
    ("wind_gust_ms", "Wind Gust", "m/s", "wind_speed", "measurement"),
    ("wind_lull_ms", "Wind Lull", "m/s", "wind_speed", "measurement"),
    ("wind_direction_deg", "Wind Direction", "°", None, "measurement"),
    ("uv_index", "UV Index", None, None, "measurement"),
    ("solar_radiation_wm2", "Solar Radiation", "W/m²", "irradiance", "measurement"),
    ("illuminance_lux", "Illuminance", "lx", "illuminance", "measurement"),
    ("rain_accumulation_mm", "Rain Accumulation", "mm", "precipitation", "measurement"),
    ("lightning_avg_dist_km", "Lightning Distance", "km", "distance", "measurement"),
    ("lightning_strike_count", "Lightning Strikes", None, None, "measurement"),
    ("battery_volts", "Battery", "V", "voltage", "measurement"),
    # Derived metrics
    ("dew_point_c", "Dew Point", "°C", "temperature", "measurement"),
    ("wet_bulb_c", "Wet Bulb Temperature", "°C", "temperature", "measurement"),
    ("delta_t_c", "Delta T", "°C", "temperature", "measurement"),
    ("feels_like_c", "Feels Like", "°C", "temperature", "measurement"),
    ("heat_index_c", "Heat Index", "°C", "temperature", "measurement"),
    ("wind_chill_c", "Wind Chill", "°C", "temperature", "measurement"),
    ("air_density_kgm3", "Air Density", "kg/m³", None, "measurement"),
    ("rain_rate_mmh", "Rain Rate", "mm/h", "precipitation_intensity", "measurement"),
    (
        "vapor_pressure_mb",
        "Vapor Pressure",
        "hPa",
        "atmospheric_pressure",
        "measurement",
    ),
    (
        "sea_level_pressure_mb",
        "Sea Level Pressure",
        "hPa",
        "atmospheric_pressure",
        "measurement",
    ),
    (
        "pressure_trend_mb",
        "Pressure Trend",
        "hPa",
        "atmospheric_pressure",
        "measurement",
    ),
    ("pressure_trend", "Pressure Trend Description", None, None, None),
    (
        "sea_level_pressure_trend_mb",
        "Sea Level Pressure Trend",
        "hPa",
        "atmospheric_pressure",
        "measurement",
    ),
    (
        "sea_level_pressure_trend",
        "Sea Level Pressure Trend Description",
        None,
        None,
        None,
    ),
    # Lightning history (persisted across restarts)
    ("lightning_last_detected", "Lightning Last Detected", None, "timestamp", None),
    ("lightning_count_3h", "Lightning Strikes (3h)", None, None, "measurement"),
    (
        "lightning_min_dist_3h_km",
        "Lightning Min Distance (3h)",
        "km",
        "distance",
        "measurement",
    ),
    (
        "lightning_max_dist_3h_km",
        "Lightning Max Distance (3h)",
        "km",
        "distance",
        "measurement",
    ),
]

_ST_STATUS_SENSORS = [
    ("rssi", "Signal Strength", "dBm", "signal_strength", "measurement"),
    ("uptime_s", "Uptime", "s", "duration", "total_increasing"),
]

_HB_STATUS_SENSORS = [
    ("rssi", "Signal Strength", "dBm", "signal_strength", "measurement"),
    ("uptime_s", "Uptime", "s", "duration", "total_increasing"),
]

_HA_DISCOVERY_MAP = {
    "obs_st": ("observation", _ST_OBS_SENSORS),
    "device_status": ("device_status", _ST_STATUS_SENSORS),
    "hub_status": ("hub_status", _HB_STATUS_SENSORS),
}

_discovered: set[str] = set()


def _device_info(serial: str) -> dict:
    serial_id = serial.replace("-", "")
    if serial.startswith("HB"):
        return {
            "identifiers": [f"tempest_{serial_id}"],
            "name": f"Tempest Hub {serial}",
            "manufacturer": "WeatherFlow",
            "model": "Tempest Hub",
        }
    return {
        "identifiers": [f"tempest_{serial_id}"],
        "name": f"Tempest {serial}",
        "manufacturer": "WeatherFlow",
        "model": "Tempest",
    }


def publish_ha_discovery(
    msg_type: str,
    serial: str,
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    log: logging.Logger,
) -> None:
    """Publish retained MQTT discovery config for every sensor of this message type."""
    if msg_type not in _HA_DISCOVERY_MAP:
        return

    key = f"{serial}:{msg_type}"
    if key in _discovered:
        return

    prefix = cfg["homeassistant"]["discovery_prefix"].rstrip("/")
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    subtopic, sensors = _HA_DISCOVERY_MAP[msg_type]
    state_topic = f"{base}/tempest-{serial}/{subtopic}"
    device = _device_info(serial)
    serial_id = serial.replace("-", "")

    for field, name, unit, device_class, state_class in sensors:
        unique_id = f"tempest_{serial_id}_{field}"
        payload: dict = {
            "name": name,
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.{field} }}}}",
            "device": device,
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if device_class:
            payload["device_class"] = device_class
        if state_class:
            payload["state_class"] = state_class

        topic = f"{prefix}/sensor/{unique_id}/config"
        try:
            result = client.publish(topic, json.dumps(payload), qos=1, retain=True)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("Discovery publish error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Discovery publish exception for %s", topic)

    _discovered.add(key)
    log.info("HA discovery published: %s / %s", serial, msg_type)


# ---------------------------------------------------------------------------
# Weather forecast  (WeatherFlow Better Forecast REST API)
# ---------------------------------------------------------------------------

_WF_ICON_TO_HA: dict[str, str] = {
    "clear-day": "sunny",
    "clear-night": "clear-night",
    "partly-cloudy-day": "partlycloudy",
    "partly-cloudy-night": "partlycloudy",
    "mostly-cloudy-day": "cloudy",
    "mostly-cloudy-night": "cloudy",
    "cloudy": "cloudy",
    "fog": "fog",
    "foggy": "fog",
    "windy": "windy",
    "rain": "rainy",
    "rainy": "rainy",
    "possibly-rainy-day": "rainy",
    "possibly-rainy-night": "rainy",
    "sleet": "snowy-rainy",
    "wintry-mix": "snowy-rainy",
    "snow": "snowy",
    "possibly-snow-day": "snowy",
    "possibly-snow-night": "snowy",
    "possibly-snow-rainy-day": "snowy-rainy",
    "possibly-snow-rainy-night": "snowy-rainy",
    "thunderstorm": "lightning",
    "possibly-thunderstorm-day": "lightning-rainy",
    "possibly-thunderstorm-night": "lightning-rainy",
    "hail": "hail",
}

_FORECAST_CC_SENSORS: list[tuple[str, str, str | None, str | None, str | None]] = [
    ("condition", "Condition", None, None, None),
    ("temperature", "Temperature", "°C", "temperature", "measurement"),
    ("humidity", "Humidity", "%", "humidity", "measurement"),
    ("wind_speed", "Wind Speed", "m/s", "wind_speed", "measurement"),
    ("wind_bearing", "Wind Bearing", "°", None, "measurement"),
    ("pressure", "Sea Level Pressure", "hPa", "atmospheric_pressure", "measurement"),
    ("dew_point", "Dew Point", "°C", "temperature", "measurement"),
]

_forecast_discovered: set[str] = set()


def _ha_condition(icon: str) -> str:
    return _WF_ICON_TO_HA.get(icon, "exceptional")


def _fetch_forecast_json(
    cfg: configparser.ConfigParser,
) -> dict | None:
    fc = cfg["forecast"]
    station_id = fc["station_id"].strip()
    api_key = fc["api_key"].strip()
    if not station_id or not api_key:
        return None
    params = urllib.parse.urlencode(
        {
            "station_id": station_id,
            "units_temp": fc["units_temp"],
            "units_wind": fc["units_wind"],
            "units_pressure": fc["units_pressure"],
            "units_precip": fc["units_precip"],
            "units_distance": fc["units_distance"],
            "api_key": api_key,
        }
    )
    url = f"https://swd.weatherflow.com/swd/rest/better_forecast?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return None


def _parse_current_conditions(cc: dict) -> dict:
    return {
        "condition": _ha_condition(cc.get("icon", "")),
        "temperature": cc.get("air_temperature"),
        "humidity": cc.get("relative_humidity"),
        "wind_speed": cc.get("wind_avg"),
        "wind_bearing": cc.get("wind_direction"),
        "pressure": cc.get("sea_level_pressure"),
        "dew_point": cc.get("dew_point"),
    }


def _parse_hourly_forecast(hourly: list[dict]) -> list[dict]:
    result = []
    for h in hourly:
        ts = h.get("time")
        result.append(
            {
                "datetime": (
                    datetime.fromtimestamp(ts, tz=UTC).isoformat()
                    if ts is not None
                    else None
                ),
                "condition": _ha_condition(h.get("icon", "")),
                "temperature": h.get("air_temperature"),
                "wind_speed": h.get("wind_avg"),
                "wind_bearing": h.get("wind_direction"),
                "precipitation": h.get("precip"),
                "precipitation_probability": h.get("precip_probability"),
                "humidity": h.get("relative_humidity"),
            }
        )
    return result


def _parse_daily_forecast(daily: list[dict]) -> list[dict]:
    result = []
    for d in daily:
        ts = d.get("day_start_local")
        result.append(
            {
                "datetime": (
                    datetime.fromtimestamp(ts, tz=UTC).isoformat()
                    if ts is not None
                    else None
                ),
                "condition": _ha_condition(d.get("icon", "")),
                "temperature": d.get("air_temp_high"),
                "templow": d.get("air_temp_low"),
                "precipitation_probability": d.get("precip_probability"),
            }
        )
    return result


def _publish_forecast_discovery(
    location: str,
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    log: logging.Logger,
) -> None:
    if location in _forecast_discovered:
        return
    prefix = cfg["homeassistant"]["discovery_prefix"].rstrip("/")
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    loc_id = location.replace("-", "_")
    curr = f"{base}/forecast-{location}/current"
    friendly = location.replace("-", " ").title()
    device = {
        "identifiers": [f"tempest_forecast_{loc_id}"],
        "name": f"Forecast {friendly}",
        "manufacturer": "WeatherFlow",
        "model": "Better Forecast API",
    }
    for field, name, unit, device_class, state_class in _FORECAST_CC_SENSORS:
        uid = f"tempest_forecast_{loc_id}_{field}"
        pl: dict = {
            "name": name,
            "unique_id": uid,
            "state_topic": curr,
            "value_template": f"{{{{ value_json.{field} }}}}",
            "device": device,
        }
        if unit:
            pl["unit_of_measurement"] = unit
        if device_class:
            pl["device_class"] = device_class
        if state_class:
            pl["state_class"] = state_class
        topic = f"{prefix}/sensor/{uid}/config"
        try:
            result = client.publish(topic, json.dumps(pl), qos=1, retain=True)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("Forecast discovery error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Forecast discovery error for %s", topic)
    for sub, name in (
        ("forecast_hourly", "Hourly Forecast"),
        ("forecast_daily", "Daily Forecast"),
    ):
        uid = f"tempest_forecast_{loc_id}_{sub}"
        arr_t = f"{base}/forecast-{location}/{sub}"
        pl = {
            "name": name,
            "unique_id": uid,
            "state_topic": arr_t,
            "value_template": "{{ value_json | length }}",
            "json_attributes_topic": arr_t,
            "json_attributes_template": ("{{ {'forecasts': value_json} | tojson }}"),
            "device": device,
        }
        topic = f"{prefix}/sensor/{uid}/config"
        try:
            result = client.publish(topic, json.dumps(pl), qos=1, retain=True)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("Forecast discovery error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Forecast discovery error for %s", topic)
    _forecast_discovered.add(location)
    p = f"sensor.forecast_{loc_id}"
    yaml_hint = (
        "\ntemplate:\n"
        "  - weather:\n"
        f"      - name: 'Forecast {friendly}'\n"
        f"        unique_id: 'tempest_forecast_{loc_id}_weather'\n"
        "        condition_template:"
        f" \"{{{{ states('{p}_condition') }}}}\"\n"
        "        temperature_template:"
        f" \"{{{{ states('{p}_temperature') | float(0) }}}}\"\n"
        "        temperature_unit: '°C'\n"
        "        humidity_template:"
        f" \"{{{{ states('{p}_humidity') | float(0) }}}}\"\n"
        "        pressure_template:"
        f" \"{{{{ states('{p}_sea_level_pressure') | float(0) }}}}\"\n"
        "        pressure_unit: 'hPa'\n"
        "        wind_speed_template:"
        f" \"{{{{ states('{p}_wind_speed') | float(0) }}}}\"\n"
        "        wind_speed_unit: 'm/s'\n"
        "        wind_bearing_template:"
        f" \"{{{{ states('{p}_wind_bearing') | float(0) }}}}\"\n"
        "        forecast_hourly_template:"
        f" \"{{{{ state_attr('{p}_hourly_forecast',"
        " 'forecasts') }}\"\n"
        "        forecast_daily_template:"
        f" \"{{{{ state_attr('{p}_daily_forecast',"
        " 'forecasts') }}\""
    )
    log.info(
        "Forecast: %d sensors discovered for '%s'."
        " To add a weather card, paste into HA configuration.yaml:%s",
        len(_FORECAST_CC_SENSORS) + 2,
        location,
        yaml_hint,
    )


def fetch_and_publish_forecast(
    client: mqtt.Client, cfg: configparser.ConfigParser, log: logging.Logger
) -> None:
    """Fetch the WeatherFlow Better Forecast and publish to MQTT."""
    data = _fetch_forecast_json(cfg)
    if data is None:
        log.warning("Forecast: fetch returned no data")
        return

    fc = cfg["forecast"]
    location = fc["location"].strip().lower().replace(" ", "-")
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    retain = cfg["mqtt"].getboolean("retain", fallback=False)
    qos = int(cfg["mqtt"]["qos"])

    cc = data.get("current_conditions", {})
    fcast = data.get("forecast", {})
    hourly_limit = int(fc["forecast_hours"])
    subtopics = [
        ("current", _parse_current_conditions(cc)),
        (
            "forecast_hourly",
            _parse_hourly_forecast(fcast.get("hourly", [])[:hourly_limit]),
        ),
        ("forecast_daily", _parse_daily_forecast(fcast.get("daily", []))),
    ]
    for subtopic, payload in subtopics:
        topic = f"{base}/forecast-{location}/{subtopic}"
        try:
            result = client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("Forecast publish error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Forecast publish exception for %s", topic)

    log.info("Forecast published → forecast-%s", location)

    if cfg["homeassistant"].getboolean("discovery"):
        _publish_forecast_discovery(location, client, cfg, log)


def _run_forecast_thread(
    client: mqtt.Client, cfg: configparser.ConfigParser, log: logging.Logger
) -> None:
    interval_s = int(cfg["forecast"]["interval_min"]) * 60
    while True:
        try:
            fetch_and_publish_forecast(client, cfg, log)
        except Exception:
            log.exception("Forecast thread error")
        time.sleep(interval_s)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

PARSERS = {
    "obs_st": ("observation", parse_obs_st),
    "rapid_wind": ("rapid_wind", parse_rapid_wind),
    "evt_precip": ("rain_start", parse_evt_precip),
    "evt_strike": ("lightning", parse_evt_strike),
    "device_status": ("device_status", parse_device_status),
    "hub_status": ("hub_status", parse_hub_status),
}


def dispatch(
    raw: bytes, client: mqtt.Client, cfg: configparser.ConfigParser, log: logging.Logger
) -> None:
    """Decode a raw UDP packet, parse it by type, and publish to MQTT."""
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.debug("Ignoring non-JSON UDP packet: %s", exc)
        return

    msg_type = msg.get("type")
    if msg_type not in PARSERS:
        log.debug("Unknown message type: %s", msg_type)
        return

    subtopic_name, parser_fn = PARSERS[msg_type]
    payload = parser_fn(msg)
    if payload is None:
        log.warning("Failed to parse %s message", msg_type)
        return

    if msg_type == "obs_st":
        payload.update(compute_obs_derived(payload, cfg))
    elif msg_type == "evt_strike":
        ts = payload.get("timestamp")
        if ts is not None:
            record_lightning_strike(int(ts), payload.get("distance_km"))

    # Derive the station/device ID
    # Hub messages use serial_number = HB-xxxxx, device messages use SK-/ST-/AR-
    serial = msg.get("serial_number", "unknown").replace(":", "-")

    base = cfg["mqtt"]["base_topic"].rstrip("/")
    topic = f"{base}/tempest-{serial}/{subtopic_name}"

    log.info("%s → %s", msg_type, topic)
    publish(client, cfg, topic, payload, log)

    if cfg["homeassistant"].getboolean("discovery"):
        publish_ha_discovery(msg_type, serial, client, cfg, log)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    """Set up MQTT and UDP socket, then run the main receive-dispatch loop."""
    # Set up MQTT
    client = make_mqtt_client(cfg, log)
    mqtt_connect(client, cfg, log)
    client.loop_start()

    if cfg["forecast"].getboolean("enabled"):
        stn = cfg["forecast"]["station_id"].strip()
        key = cfg["forecast"]["api_key"].strip()
        if stn and key:
            threading.Thread(
                target=_run_forecast_thread,
                args=(client, cfg, log),
                daemon=True,
                name="forecast",
            ).start()
            log.info(
                "Forecast thread started (interval: %s min)",
                cfg["forecast"]["interval_min"],
            )
        else:
            log.warning(
                "Forecast enabled but station_id/api_key not configured — skipping"
            )

    # Set up UDP socket
    udp_cfg = cfg["udp"]
    addr = udp_cfg["listen_address"]
    port = int(udp_cfg["listen_port"])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((addr, port))
    sock.settimeout(5.0)

    log.info("Listening for Tempest UDP broadcasts on %s:%s", addr, port)
    log.info(
        "Publishing to MQTT broker %s:%s  base topic: %s",
        cfg["mqtt"]["broker"],
        cfg["mqtt"]["port"],
        cfg["mqtt"]["base_topic"],
    )

    try:
        while True:
            try:
                data, remote = sock.recvfrom(4096)
                log.debug("UDP packet from %s (%d bytes)", remote, len(data))
                dispatch(data, client, cfg, log)
            except TimeoutError:
                # Heartbeat — keeps the loop alive and lets MQTT ping
                pass
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("Unexpected error")
    except KeyboardInterrupt:
        log.info("Shutting down…")
    finally:
        sock.close()
        client.loop_stop()
        client.disconnect()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the datalogger."""
    parser = argparse.ArgumentParser(
        description="WeatherFlow Tempest UDP → MQTT datalogger"
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

    init_pressure(cfg, args.config, log)
    init_lightning(cfg, args.config, log)
    run(cfg, log)


if __name__ == "__main__":
    main()
