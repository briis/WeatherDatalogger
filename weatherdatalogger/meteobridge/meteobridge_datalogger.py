#!/usr/bin/env python3
"""
Meteobridge HTTP → MQTT Datalogger.

Polls a Meteobridge's local REST template API — wired directly to the same
Vantage Vue ISS as the davis-vantage-receiver ESPHome device, plus the
Meteobridge unit's own onboard barometer/indoor sensor and a second attached
station providing solar/UV/lightning — and publishes a full observation to
MQTT under the topic:

    weatherdatalogger/meteobridge-<mac>/observation

This is a full station integration: db_writer.py picks up the observation
topic automatically and writes it to the `realtime`/`history` tables like
any other station. It supersedes the old rain-correction-only role this
service used to play (pushing set_daily_rain/set_rain_rate into the Davis
receiver's own MQTT control topics) — see AGENT.md "Rain accumulation &
rate". That correction was never depended on: Davis's own rain fields are
computed standalone from its RF tip counter, so retiring the push has no
effect on that device either way.

Which station supplies which combined_realtime field is controlled by the
`station_roles` table, not by this script — see database/02_create_tables.sql.
Point any role at `meteobridge` there to prefer this station's reading.

Fields published (flat JSON object, SI units) mirror the columns in
`realtime`/`history` (see db_writer.py _OBS_FIELDS): wind, pressure
(+ 3h trend), outdoor temperature/humidity/dew point/wet bulb/heat index/
wind chill, solar/UV, rain, indoor temperature/humidity, and a best-effort
lightning summary. illuminance_lux and battery_volts/battery_low have no
known Meteobridge macro and are omitted (NULL in the database).

Usage:
    python3 meteobridge_datalogger.py [--config config.ini]
"""

import argparse
import base64
import configparser
import contextlib
import json
import logging
import math
import sys
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
    "meteobridge": {
        "enabled": "false",  # set true to enable this service
        "host": "",
        "port": "80",
        # "meteobridge" is Meteobridge's own factory-default admin username;
        # most units require HTTP basic auth for the template API even
        # without other security configured. Set username to empty to send
        # the request without an Authorization header at all.
        "username": "meteobridge",
        "password": "",
        "interval_s": "60",
        "timeout_s": "10",
        # Language for wind_beaufort_description — "en" or "da", same
        # convention/wording as davis-vantage-receiver.yaml's beaufort_en/da.
        "language": "en",
        # Directory for the persisted lightning-window state file. Empty =
        # same directory as the config file.
        "data_dir": "",
    },
    "mqtt": {
        "broker": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "tls": "false",
        "base_topic": "weatherdatalogger",
        "client_id": "meteobridge-datalogger",
        "retain": "false",
        "qos": "0",
    },
    "logging": {
        "level": "INFO",
        "file": "",
    },
    "homeassistant": {
        "discovery": "false",
        "discovery_prefix": "homeassistant",
    },
}

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(level_str: str, log_file: str) -> logging.Logger:
    """Configure root logger and return the named 'meteobridge' logger."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return logging.getLogger("meteobridge")


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


def _enabled_key_present(path: str, section: str) -> bool:
    """
    Return True if config.ini itself (not DEFAULT_CONFIG) sets `enabled` for `section`.

    Distinguishes "explicitly disabled" from "config.ini predates the
    `enabled` flag" so upgraded installs get a clear one-time warning
    instead of silently going idle.
    """
    if not Path(path).exists():
        return False
    raw = configparser.ConfigParser()
    raw.read(path)
    return raw.has_option(section, "enabled")


# ---------------------------------------------------------------------------
# Meteobridge template — square-bracket macros substituted server-side.
# Deliberately quote-free CSV, not JSON: real hardware backslash-escapes
# every quote in JSON-shaped template output (some Meteobridge firmware
# applies PHP/CGI-style addslashes()), breaking json.loads. A ":fallback"
# suffix on each macro means one missing/unavailable sensor degrades that
# single field to a default instead of losing the whole poll — validated
# against real hardware; see the field-by-field notes below.
#
# Macro suffixes validated live against real hardware (2026-07):
#   wind0wind-min1/-avg1/-max1  — lull/avg/gust are self-consistent
#     (lull <= avg <= gust) against a live reading
#   thb0press-delta3h / thb0seapress-delta3h — both returned the same delta,
#     which is physically expected (the sea-level offset is ~constant, so
#     the *change* over 3h should match at both altitudes)
#   th0dew < th0wetbulb < th0temp — self-consistent against a live reading
#   lgt0dist-act — correctly falls back to "-" (not 0) when there's no
#     current strike, so a 0 km reading is never confused with "no data"
#   lgt0total-act returned a nonsensical "0%" — -daysum (mirroring
#     rain0total's convention) returns a clean numeric 0 instead
#   lgt0dist-time (hoped-for last-strike timestamp) is not supported —
#     falls back cleanly, so lightning_last_detected is derived client-side
#     instead (see update_lightning() below)
# See https://www.meteobridge.com/wiki/index.php?title=Templates for the
# macro suffix reference.
# ---------------------------------------------------------------------------

_TEMPLATE_FIELDS: tuple[str, ...] = (
    "mac",
    "epoch",
    "wind_lull_ms",
    "wind_avg_ms",
    "wind_gust_ms",
    "wind_direction_deg",
    "station_pressure_mb",
    "sea_level_pressure_mb",
    "station_pressure_trend_3h_mb",
    "sea_level_pressure_trend_3h_mb",
    "air_temperature_c",
    "relative_humidity_pct",
    "dew_point_c",
    "wet_bulb_c",
    "heat_index_c",
    "wind_chill_c",
    "uv_index",
    "solar_radiation_wm2",
    "rain_rate_mmh",
    "rain_accumulation_mm",
    "indoor_temperature_c",
    "indoor_humidity_pct",
    "lightning_distance_km",
    "lightning_count_today",
    "pm_10_ugm3",
    "pm_10_1h_ugm3",
    "pm_2p5_ugm3",
    "pm_2p5_1h_ugm3",
    "pm_1_ugm3",
    "pm_1_1h_ugm3",
)

MB_TEMPLATE = (
    "[mbsystem-mac:-],[epoch],"
    "[wind0wind-min1:0],[wind0wind-avg1:0],[wind0wind-max1:0],[wind0dir-act:0],"
    "[thb0press-act:0],[thb0seapress-act:0],"
    "[thb0press-delta3h:0],[thb0seapress-delta3h:0],"
    "[th0temp-act:0],[th0hum-act:0],[th0dew-act:0],[th0wetbulb-act:0],"
    "[th0heatindex-act:0],[wind0chill-act:0],"
    "[uv0index-act:0],[sol0rad-act:0],"
    "[rain0rate-act:0],[rain0total-daysum:0],"
    "[thb0temp-act:0],[thb0hum-act:0],"
    "[lgt0dist-act:-],[lgt0total-daysum:0],"
    # air0pm/air1pm/air2pm = PM10/PM2.5/PM1.0 respectively — confirmed against
    # live hardware by physical ordering (PM1.0 <= PM2.5 <= PM10 always
    # holds), which contradicts an earlier, differently-wired service's SQL
    # template that had pm1/pm10 swapped. -avg60 (60 min) is the longest
    # averaging window this particular sensor supports — avg180/avg1440
    # (3h/24h) both silently returned 0 against real hardware, so 3h/24h/
    # NowCast are computed client-side from a persisted rolling buffer
    # instead (see record_air_quality()/nowcast()).
    "[air0pm-act:0],[air0pm-avg60:0],"
    "[air1pm-act:0],[air1pm-avg60:0],"
    "[air2pm-act:0],[air2pm-avg60:0]"
)


def _auth_headers(mb: configparser.SectionProxy) -> dict[str, str]:
    """Build a preemptive HTTP Basic Auth header, or none if username is blank."""
    username = mb["username"].strip()
    if not username:
        return {}
    token = base64.b64encode(f"{username}:{mb['password']}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _to_float(raw: str) -> float | None:
    raw = raw.strip()
    if raw in ("-", ""):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def fetch_raw(
    cfg: configparser.ConfigParser, log: logging.Logger
) -> dict[str, str] | None:
    """Fetch the template response from Meteobridge; return field name -> raw string."""
    mb = cfg["meteobridge"]
    host = mb["host"].strip()
    port = int(mb["port"])
    timeout = int(mb["timeout_s"])
    query = urllib.parse.urlencode({"template": MB_TEMPLATE})
    url = f"http://{host}:{port}/cgi-bin/template.cgi?{query}"

    try:
        req = urllib.request.Request(url, headers=_auth_headers(mb))  # noqa: S310
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode().strip()
    except Exception:  # noqa: BLE001
        log.warning("Meteobridge request failed (%s)", url)
        return None

    parts = body.split(",")
    if len(parts) != len(_TEMPLATE_FIELDS):
        log.warning(
            "Meteobridge response has unexpected shape (%d fields, expected %d): %r",
            len(parts),
            len(_TEMPLATE_FIELDS),
            body,
        )
        return None

    return dict(zip(_TEMPLATE_FIELDS, parts, strict=True))


# ---------------------------------------------------------------------------
# Beaufort wind scale — same WMO thresholds and English/Danish wording as
# davis-vantage-receiver.yaml (lines 540-565), computed client-side from
# wind_avg_ms rather than trusting Meteobridge's own "=bft" unit converter,
# so the numbers/wording match exactly regardless of which station a role
# currently points at.
# ---------------------------------------------------------------------------

_BEAUFORT_THRESHOLDS_MS: tuple[float, ...] = (
    0.5,
    1.6,
    3.4,
    5.5,
    8.0,
    10.8,
    13.9,
    17.2,
    20.8,
    24.5,
    28.5,
    32.7,
)
_BEAUFORT_EN: tuple[str, ...] = (
    "Calm",
    "Light air",
    "Light breeze",
    "Gentle breeze",
    "Moderate breeze",
    "Fresh breeze",
    "Strong breeze",
    "Near gale",
    "Gale",
    "Strong gale",
    "Storm",
    "Violent storm",
    "Hurricane",
)
_BEAUFORT_DA: tuple[str, ...] = (
    "Stille",
    "Næsten stille",
    "Svag vind",
    "Let vind",
    "Jævn vind",
    "Frisk vind",
    "Hård vind",
    "Stiv kuling",
    "Hård kuling",
    "Stormende kuling",
    "Storm",
    "Voldsom storm",
    "Orkan",
)


def _beaufort(wind_ms: float, language: str) -> tuple[int, str]:
    force = next(
        (i for i, t in enumerate(_BEAUFORT_THRESHOLDS_MS) if wind_ms < t),
        len(_BEAUFORT_THRESHOLDS_MS),
    )
    names = _BEAUFORT_DA if language == "da" else _BEAUFORT_EN
    return force, names[force]


# ---------------------------------------------------------------------------
# Derived metrics not directly available from Meteobridge — same formulas as
# tempest_datalogger.py (source: apidocs.tempestwx.com/reference/derived-metrics)
# ---------------------------------------------------------------------------

_R_DRY_AIR = 287.058  # J/(kg·K)
_HI_TEMP_MIN_F = 80.0  # heat index valid above this (°F)
_HI_RH_MIN = 40.0  # heat index valid above this (%)
_WC_TEMP_MAX_F = 50.0  # wind chill valid below this (°F)
_WC_WIND_MIN_MPH = 3.0  # wind chill valid above this (mph)
_PRESSURE_TREND_MB = 1.0  # threshold for Rising/Falling label


def _c_to_f(t: float) -> float:
    return t * 9.0 / 5.0 + 32.0


def _ms_to_mph(v: float) -> float:
    return v * 2.23694


def _vapor_pressure_mb(t_c: float, rh: float) -> float:
    return round((rh / 100.0) * 6.112 * math.exp(17.67 * t_c / (t_c + 243.5)), 2)


def _air_density(p_mb: float, t_c: float) -> float:
    return round(p_mb * 100.0 / (_R_DRY_AIR * (t_c + 273.15)), 3)


def _feels_like_c(
    t_c: float,
    rh: float,
    wind_ms: float,
    heat_index_c: float | None,
    wind_chill_c: float | None,
) -> float:
    """Pick heat index, wind chill, or plain temp using tempest's thresholds."""
    t_f = _c_to_f(t_c)
    v_mph = _ms_to_mph(wind_ms)
    if t_f >= _HI_TEMP_MIN_F and rh >= _HI_RH_MIN and heat_index_c is not None:
        return heat_index_c
    if t_f <= _WC_TEMP_MAX_F and v_mph > _WC_WIND_MIN_MPH and wind_chill_c is not None:
        return wind_chill_c
    return round(t_c, 1)


def _pressure_trend_label(delta_mb: float | None) -> str | None:
    if delta_mb is None:
        return None
    if delta_mb <= -_PRESSURE_TREND_MB:
        return "Falling"
    if delta_mb >= _PRESSURE_TREND_MB:
        return "Rising"
    return "Steady"


# ---------------------------------------------------------------------------
# Lightning window — Meteobridge only exposes a cumulative daily strike
# counter and the *current* strike distance (no per-strike timestamp; the
# "-time" macro suffix was tried against real hardware and doesn't work),
# so new strikes are detected by watching lgt0total-daysum increase between
# polls, same rolling-3h-summary shape as tempest_datalogger.py's
# lightning_summary() but fed from a polled counter instead of discrete
# WeatherFlow UDP strike events. Persisted across restarts like tempest's.
# ---------------------------------------------------------------------------

_LIGHTNING_WINDOW_S = 3 * 3600  # 3-hour summary window
_LIGHTNING_KEEP_S = 24 * 3600  # retain events for up to 24 hours

_lightning_events: list[dict] = []
_lightning_last_count: list[int | None] = [None]
_lightning_file: list[Path | None] = [None]  # mutable cell avoids `global`


def _lightning_data_path(cfg: configparser.ConfigParser, config_path: str) -> Path:
    data_dir = cfg["meteobridge"].get("data_dir", "").strip()
    if data_dir:
        return Path(data_dir) / "meteobridge_lightning.json"
    return Path(config_path).resolve().parent / "meteobridge_lightning.json"


def _load_lightning(path: Path) -> tuple[list[dict], int | None]:
    if not path.exists():
        return [], None
    try:
        data = json.loads(path.read_text())
        cutoff = int(time.time()) - _LIGHTNING_KEEP_S
        events = [e for e in data.get("events", []) if e.get("ts", 0) >= cutoff]
        return events, data.get("last_count")
    except Exception:  # noqa: BLE001
        return [], None


def _save_lightning() -> None:
    path = _lightning_file[0]
    if path is None:
        return
    with contextlib.suppress(Exception):
        path.write_text(
            json.dumps(
                {"events": _lightning_events, "last_count": _lightning_last_count[0]}
            )
        )


def init_lightning(
    cfg: configparser.ConfigParser, config_path: str, log: logging.Logger
) -> None:
    """Load persisted lightning window state and configure the storage path."""
    path = _lightning_data_path(cfg, config_path)
    _lightning_file[0] = path
    events, last_count = _load_lightning(path)
    _lightning_events.clear()
    _lightning_events.extend(events)
    _lightning_last_count[0] = last_count
    log.info("Lightning history: %d event(s) loaded from %s", len(events), path)


def update_lightning(now_ts: int, count_today: int, dist_km: float | None) -> None:
    """
    Record one synthetic event per strike detected since the last poll.

    A jump in the daily counter can represent several strikes at once — the
    counter alone can't attribute a distance to each individually, so every
    strike in the jump is recorded at the current poll's distance reading. A
    *decrease* means Meteobridge's own local-midnight reset fired; no new
    strikes are assumed for that poll.
    """
    last = _lightning_last_count[0]
    if last is not None and count_today > last:
        _lightning_events.extend(
            {"ts": now_ts, "dist": dist_km} for _ in range(count_today - last)
        )
    _lightning_last_count[0] = count_today

    cutoff = now_ts - _LIGHTNING_KEEP_S
    while _lightning_events and _lightning_events[0]["ts"] < cutoff:
        _lightning_events.pop(0)
    _save_lightning()


def lightning_summary(now_ts: int) -> dict:
    """Return 3h lightning summary fields for inclusion in the observation payload."""
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


# ---------------------------------------------------------------------------
# Air quality — US EPA AQI / EU CAQI, same breakpoint tables and formulas as
# airlink_datalogger.py (each service stays self-contained, so these are
# duplicated rather than shared). Meteobridge's own PM sensor only buffers a
# 60-min averaging window (avg180/avg1440 both silently returned 0 against
# real hardware) — 3h/24h averages and the 12h-weighted EPA NowCast (AQI's
# input) are computed client-side from a persisted rolling sample buffer,
# same persisted-state pattern as the lightning window above.
# ---------------------------------------------------------------------------

_PM25_BREAKPOINTS: tuple[tuple[float, float, int, int], ...] = (
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 350.4, 301, 400),
    (350.5, 500.4, 401, 500),
)

_PM10_BREAKPOINTS: tuple[tuple[int, int, int, int], ...] = (
    (0, 54, 0, 50),
    (55, 154, 51, 100),
    (155, 254, 101, 150),
    (255, 354, 151, 200),
    (355, 424, 201, 300),
    (425, 504, 301, 400),
    (505, 604, 401, 500),
)


def _aqi_pm2p5(nowcast_ugm3: float | None) -> int | None:
    """Compute PM2.5 AQI from NowCast concentration using US EPA breakpoints."""
    if nowcast_ugm3 is None:
        return None
    c = round(nowcast_ugm3, 1)
    for c_lo, c_hi, aqi_lo, aqi_hi in _PM25_BREAKPOINTS:
        if c_lo <= c <= c_hi:
            return round((aqi_hi - aqi_lo) / (c_hi - c_lo) * (c - c_lo) + aqi_lo)
    return None


def _aqi_pm10(nowcast_ugm3: float | None) -> int | None:
    """Compute PM10 AQI from NowCast concentration using US EPA breakpoints."""
    if nowcast_ugm3 is None:
        return None
    c = round(nowcast_ugm3)
    for c_lo, c_hi, aqi_lo, aqi_hi in _PM10_BREAKPOINTS:
        if c_lo <= c <= c_hi:
            return round((aqi_hi - aqi_lo) / (c_hi - c_lo) * (c - c_lo) + aqi_lo)
    return None


_CAQI_PM25_BREAKPOINTS: tuple[tuple[float, float, int, int], ...] = (
    (0.0, 15.0, 0, 25),
    (15.0, 30.0, 25, 50),
    (30.0, 55.0, 50, 75),
    (55.0, 110.0, 75, 100),
    (110.0, 330.0, 100, 200),
)

_CAQI_PM10_BREAKPOINTS: tuple[tuple[float, float, int, int], ...] = (
    (0.0, 25.0, 0, 25),
    (25.0, 50.0, 25, 50),
    (50.0, 90.0, 50, 75),
    (90.0, 180.0, 75, 100),
    (180.0, 540.0, 100, 200),
)


def _caqi_pm2p5(concentration_ugm3: float | None) -> int | None:
    """Compute the CAQI PM2.5 sub-index from current concentration."""
    if concentration_ugm3 is None:
        return None
    c = round(concentration_ugm3, 1)
    for c_lo, c_hi, idx_lo, idx_hi in _CAQI_PM25_BREAKPOINTS:
        if c_lo <= c <= c_hi:
            return round((idx_hi - idx_lo) / (c_hi - c_lo) * (c - c_lo) + idx_lo)
    return 200  # beyond even the extrapolated ceiling — cap rather than omit


def _caqi_pm10(concentration_ugm3: float | None) -> int | None:
    """Compute the CAQI PM10 sub-index from current concentration."""
    if concentration_ugm3 is None:
        return None
    c = round(concentration_ugm3)
    for c_lo, c_hi, idx_lo, idx_hi in _CAQI_PM10_BREAKPOINTS:
        if c_lo <= c <= c_hi:
            return round((idx_hi - idx_lo) / (c_hi - c_lo) * (c - c_lo) + idx_lo)
    return 200


_AQ_KEEP_S = 24 * 3600  # retain samples for up to 24 hours
_NOWCAST_HOURS = 12  # EPA NowCast uses the most recent 12 hourly averages

_aq_samples: list[dict] = []
_aq_file: list[Path | None] = [None]  # mutable cell avoids `global`


def _aq_data_path(cfg: configparser.ConfigParser, config_path: str) -> Path:
    data_dir = cfg["meteobridge"].get("data_dir", "").strip()
    if data_dir:
        return Path(data_dir) / "meteobridge_airquality.json"
    return Path(config_path).resolve().parent / "meteobridge_airquality.json"


def _load_aq(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        cutoff = int(time.time()) - _AQ_KEEP_S
        return [s for s in data.get("samples", []) if s.get("ts", 0) >= cutoff]
    except Exception:  # noqa: BLE001
        return []


def _save_aq() -> None:
    path = _aq_file[0]
    if path is None:
        return
    with contextlib.suppress(Exception):
        path.write_text(json.dumps({"samples": _aq_samples}))


def init_air_quality(
    cfg: configparser.ConfigParser, config_path: str, log: logging.Logger
) -> None:
    """Load the persisted PM sample buffer and configure the storage path."""
    path = _aq_data_path(cfg, config_path)
    _aq_file[0] = path
    samples = _load_aq(path)
    _aq_samples.clear()
    _aq_samples.extend(samples)
    log.info("Air quality history: %d sample(s) loaded from %s", len(samples), path)


def record_air_quality(
    now_ts: int, pm1: float | None, pm25: float | None, pm10: float | None
) -> None:
    """Append one PM sample to the persisted rolling buffer."""
    _aq_samples.append({"ts": now_ts, "pm1": pm1, "pm25": pm25, "pm10": pm10})
    cutoff = now_ts - _AQ_KEEP_S
    while _aq_samples and _aq_samples[0]["ts"] < cutoff:
        _aq_samples.pop(0)
    _save_aq()


def _window_avg(now_ts: int, window_s: int, key: str) -> float | None:
    cutoff = now_ts - window_s
    vals = [s[key] for s in _aq_samples if s["ts"] >= cutoff and s.get(key) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _hourly_buckets(now_ts: int, key: str) -> list[float | None]:
    """Return the most recent _NOWCAST_HOURS complete-hour averages, newest first."""
    buckets: list[float | None] = []
    for h in range(_NOWCAST_HOURS):
        hi = now_ts - h * 3600
        lo = hi - 3600
        vals = [
            s[key] for s in _aq_samples if lo <= s["ts"] < hi and s.get(key) is not None
        ]
        buckets.append(round(sum(vals) / len(vals), 1) if vals else None)
    return buckets


def _nowcast(now_ts: int, key: str) -> float | None:
    """
    Weighted average of the last 12 hourly averages, EPA NowCast style.

    Weight is driven by how much concentration has varied across the
    available hours. Requires at least 2 of the most recent 3 hours to have
    data.
    """
    buckets = _hourly_buckets(now_ts, key)
    if sum(1 for b in buckets[:3] if b is not None) < 2:  # noqa: PLR2004
        return None
    present = [(i, b) for i, b in enumerate(buckets) if b is not None]
    if not present:
        return None
    c_max = max(b for _, b in present)
    c_min = min(b for _, b in present)
    weight = 1.0 if c_max == 0 else max(1.0 - (c_max - c_min) / c_max, 0.5)
    numerator = sum((weight**i) * b for i, b in present)
    denominator = sum(weight**i for i, _ in present)
    return round(numerator / denominator, 1) if denominator else None


def air_quality_summary(now_ts: int) -> dict:
    """Return 3h/24h averages, NowCast, AQI and CAQI for inclusion in the payload."""
    pm25_3h = _window_avg(now_ts, 3 * 3600, "pm25")
    pm25_24h = _window_avg(now_ts, _AQ_KEEP_S, "pm25")
    pm10_3h = _window_avg(now_ts, 3 * 3600, "pm10")
    pm10_24h = _window_avg(now_ts, _AQ_KEEP_S, "pm10")
    pm25_nowcast = _nowcast(now_ts, "pm25")
    pm10_nowcast = _nowcast(now_ts, "pm10")
    current_pm25 = _aq_samples[-1]["pm25"] if _aq_samples else None
    current_pm10 = _aq_samples[-1]["pm10"] if _aq_samples else None
    return {
        "pm_2p5_3h_ugm3": pm25_3h,
        "pm_2p5_24h_ugm3": pm25_24h,
        "pm_2p5_nowcast_ugm3": pm25_nowcast,
        "pm_10_3h_ugm3": pm10_3h,
        "pm_10_24h_ugm3": pm10_24h,
        "pm_10_nowcast_ugm3": pm10_nowcast,
        "aqi_pm2p5": _aqi_pm2p5(pm25_nowcast),
        "aqi_pm10": _aqi_pm10(pm10_nowcast),
        "caqi_pm2p5": _caqi_pm2p5(current_pm25),
        "caqi_pm10": _caqi_pm10(current_pm10),
    }


# ---------------------------------------------------------------------------
# Observation assembly
# ---------------------------------------------------------------------------


def build_observation(
    raw: dict[str, str], cfg: configparser.ConfigParser, log: logging.Logger
) -> dict | None:
    """Turn a raw template response into a flat observation payload, or None."""
    mac = raw["mac"].strip()
    if mac in ("-", ""):
        log.warning("Meteobridge returned no MAC address — skipping this poll")
        return None
    station_id = mac.replace(":", "-")

    try:
        ts = int(float(raw["epoch"]))
    except ValueError:
        ts = int(time.time())

    wind_avg = _to_float(raw["wind_avg_ms"]) or 0.0
    air_temp = _to_float(raw["air_temperature_c"])
    rh = _to_float(raw["relative_humidity_pct"])
    station_pressure = _to_float(raw["station_pressure_mb"])
    wet_bulb = _to_float(raw["wet_bulb_c"])
    heat_index = _to_float(raw["heat_index_c"])
    wind_chill = _to_float(raw["wind_chill_c"])

    language = cfg["meteobridge"]["language"].strip().lower()
    beaufort_force, beaufort_desc = _beaufort(wind_avg, language)

    payload: dict = {
        "serial_number": station_id,
        "timestamp": ts,
        "wind_lull_ms": _to_float(raw["wind_lull_ms"]),
        "wind_avg_ms": wind_avg,
        "wind_gust_ms": _to_float(raw["wind_gust_ms"]),
        "wind_direction_deg": _to_float(raw["wind_direction_deg"]),
        "wind_beaufort": beaufort_force,
        "wind_beaufort_description": beaufort_desc,
        "station_pressure_mb": station_pressure,
        "sea_level_pressure_mb": _to_float(raw["sea_level_pressure_mb"]),
        "pressure_trend_mb": _to_float(raw["station_pressure_trend_3h_mb"]),
        "sea_level_pressure_trend_mb": _to_float(
            raw["sea_level_pressure_trend_3h_mb"]
        ),
        "air_temperature_c": air_temp,
        "relative_humidity_pct": rh,
        "dew_point_c": _to_float(raw["dew_point_c"]),
        "wet_bulb_c": wet_bulb,
        "heat_index_c": heat_index,
        "wind_chill_c": wind_chill,
        "uv_index": _to_float(raw["uv_index"]),
        "solar_radiation_wm2": _to_float(raw["solar_radiation_wm2"]),
        "rain_rate_mmh": _to_float(raw["rain_rate_mmh"]),
        "rain_accumulation_mm": _to_float(raw["rain_accumulation_mm"]),
        "indoor_temperature_c": _to_float(raw["indoor_temperature_c"]),
        "indoor_humidity_pct": _to_float(raw["indoor_humidity_pct"]),
    }
    payload["pressure_trend"] = _pressure_trend_label(payload["pressure_trend_mb"])
    payload["sea_level_pressure_trend"] = _pressure_trend_label(
        payload["sea_level_pressure_trend_mb"]
    )

    if air_temp is not None and rh is not None:
        payload["vapor_pressure_mb"] = _vapor_pressure_mb(air_temp, rh)
        payload["feels_like_c"] = _feels_like_c(
            air_temp, rh, wind_avg, heat_index, wind_chill
        )
    if air_temp is not None and wet_bulb is not None:
        payload["delta_t_c"] = round(air_temp - wet_bulb, 1)
    if station_pressure is not None and air_temp is not None:
        payload["air_density_kgm3"] = _air_density(station_pressure, air_temp)

    dist_km = _to_float(raw["lightning_distance_km"])
    count_today = int(_to_float(raw["lightning_count_today"]) or 0)
    update_lightning(ts, count_today, dist_km)
    payload.update(lightning_summary(ts))

    pm1 = _to_float(raw["pm_1_ugm3"])
    pm25 = _to_float(raw["pm_2p5_ugm3"])
    pm10 = _to_float(raw["pm_10_ugm3"])
    payload["pm_1_ugm3"] = pm1
    payload["pm_2p5_ugm3"] = pm25
    payload["pm_2p5_1h_ugm3"] = _to_float(raw["pm_2p5_1h_ugm3"])
    payload["pm_10_ugm3"] = pm10
    payload["pm_10_1h_ugm3"] = _to_float(raw["pm_10_1h_ugm3"])
    record_air_quality(ts, pm1, pm25, pm10)
    payload.update(air_quality_summary(ts))

    return payload


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
    """Serialise payload as JSON and publish; log but do not raise on error."""
    m = cfg["mqtt"]
    retain = m.getboolean("retain", fallback=False)
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
_METEOBRIDGE_SENSORS: list[tuple[str, str, str | None, str | None, str | None]] = [
    ("wind_lull_ms", "Wind Lull", "m/s", "wind_speed", "measurement"),
    ("wind_avg_ms", "Wind Speed", "m/s", "wind_speed", "measurement"),
    ("wind_gust_ms", "Wind Gust", "m/s", "wind_speed", "measurement"),
    (
        "wind_direction_deg",
        "Wind Direction",
        "°",
        "wind_direction",
        "measurement_angle",
    ),
    ("wind_beaufort", "Beaufort Scale", None, None, "measurement"),
    ("wind_beaufort_description", "Beaufort Description", None, None, None),
    ("station_pressure_mb", "Pressure", "hPa", "atmospheric_pressure", "measurement"),
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
    ("air_temperature_c", "Temperature", "°C", "temperature", "measurement"),
    ("relative_humidity_pct", "Humidity", "%", "humidity", "measurement"),
    ("dew_point_c", "Dew Point", "°C", "temperature", "measurement"),
    ("wet_bulb_c", "Wet Bulb Temperature", "°C", "temperature", "measurement"),
    ("delta_t_c", "Delta T", "°C", "temperature", "measurement"),
    ("feels_like_c", "Feels Like", "°C", "temperature", "measurement"),
    ("heat_index_c", "Heat Index", "°C", "temperature", "measurement"),
    ("wind_chill_c", "Wind Chill", "°C", "temperature", "measurement"),
    ("uv_index", "UV Index", None, None, "measurement"),
    ("solar_radiation_wm2", "Solar Radiation", "W/m²", "irradiance", "measurement"),
    ("rain_rate_mmh", "Rain Rate", "mm/h", "precipitation_intensity", "measurement"),
    ("rain_accumulation_mm", "Rain Accumulation", "mm", "precipitation", "measurement"),
    ("indoor_temperature_c", "Indoor Temperature", "°C", "temperature", "measurement"),
    ("indoor_humidity_pct", "Indoor Humidity", "%", "humidity", "measurement"),
    (
        "vapor_pressure_mb",
        "Vapor Pressure",
        "hPa",
        "atmospheric_pressure",
        "measurement",
    ),
    ("air_density_kgm3", "Air Density", "kg/m³", None, "measurement"),
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
    ("pm_1_ugm3", "PM1.0", "µg/m³", "pm1", "measurement"),
    ("pm_2p5_ugm3", "PM2.5", "µg/m³", "pm25", "measurement"),
    ("pm_2p5_1h_ugm3", "PM2.5 (1-hour average)", "µg/m³", "pm25", "measurement"),
    ("pm_2p5_3h_ugm3", "PM2.5 (3-hour average)", "µg/m³", "pm25", "measurement"),
    ("pm_2p5_24h_ugm3", "PM2.5 (24-hour average)", "µg/m³", "pm25", "measurement"),
    ("pm_2p5_nowcast_ugm3", "PM2.5 NowCast", "µg/m³", "pm25", "measurement"),
    ("pm_10_ugm3", "PM10", "µg/m³", "pm10", "measurement"),
    ("pm_10_1h_ugm3", "PM10 (1-hour average)", "µg/m³", "pm10", "measurement"),
    ("pm_10_3h_ugm3", "PM10 (3-hour average)", "µg/m³", "pm10", "measurement"),
    ("pm_10_24h_ugm3", "PM10 (24-hour average)", "µg/m³", "pm10", "measurement"),
    ("pm_10_nowcast_ugm3", "PM10 NowCast", "µg/m³", "pm10", "measurement"),
    ("aqi_pm2p5", "AQI (PM2.5)", None, "aqi", "measurement"),
    ("aqi_pm10", "AQI (PM10)", None, "aqi", "measurement"),
    ("caqi_pm2p5", "CAQI (PM2.5)", None, "aqi", "measurement"),
    ("caqi_pm10", "CAQI (PM10)", None, "aqi", "measurement"),
]

_SENSOR_ICON_OVERRIDES = {
    "wind_beaufort": "mdi:speedometer",
    "pressure_trend": "mdi:trending-up",
    "sea_level_pressure_trend": "mdi:trending-up",
    "pressure_trend_mb": "mdi:arrow-collapse",
    "sea_level_pressure_trend_mb": "mdi:arrow-collapse",
    "air_density_kgm3": "mdi:weight-kilogram",
}

_discovered: set[str] = set()


def _device_info(station_id: str) -> dict:
    return {
        "identifiers": [f"meteobridge_{station_id}"],
        "name": f"Meteobridge {station_id}",
        "manufacturer": "Smartbedded",
        "model": "Meteobridge",
    }


def publish_ha_discovery(
    station_id: str,
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    log: logging.Logger,
) -> None:
    """Publish retained MQTT discovery config for all Meteobridge sensors (once)."""
    if station_id in _discovered:
        return

    prefix = cfg["homeassistant"]["discovery_prefix"].rstrip("/")
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    state_topic = f"{base}/meteobridge-{station_id}/observation"
    device = _device_info(station_id)

    for field, name, unit, device_class, state_class in _METEOBRIDGE_SENSORS:
        unique_id = f"meteobridge_{station_id}_{field}"
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
        icon = _SENSOR_ICON_OVERRIDES.get(field)
        if icon:
            payload["icon"] = icon

        topic = f"{prefix}/sensor/{unique_id}/config"
        try:
            result = client.publish(topic, json.dumps(payload), qos=1, retain=True)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("Discovery publish error rc=%s topic=%s", result.rc, topic)
        except Exception:
            log.exception("Discovery publish exception for %s", topic)

    _discovered.add(station_id)
    log.info(
        "HA discovery published: Meteobridge %s (%d sensors)",
        station_id,
        len(_METEOBRIDGE_SENSORS),
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, config_path: str, log: logging.Logger) -> None:
    """Connect to MQTT, then poll Meteobridge on a fixed interval."""
    mb = cfg["meteobridge"]
    if not mb.getboolean("enabled"):
        if not _enabled_key_present(config_path, "meteobridge"):
            log.warning(
                "[meteobridge] enabled is not set in config.ini — defaulting "
                "to disabled as of this version (previously ran whenever "
                "`host` was set). Add 'enabled = true' under [meteobridge] "
                "to keep logging Meteobridge data."
            )
        else:
            log.info("[meteobridge] enabled = false — exiting")
        return

    client = make_mqtt_client(cfg, log)
    mqtt_connect(client, cfg, log)
    client.loop_start()

    host = mb["host"].strip()
    if not host:
        log.error(
            "Meteobridge host is not configured. "
            "Set [meteobridge] host in config.ini and restart."
        )
        client.loop_stop()
        client.disconnect()
        return

    interval_s = int(mb["interval_s"])
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    ha_discovery = cfg["homeassistant"].getboolean("discovery")

    log.info(
        "Polling Meteobridge at %s:%s every %s s  base topic: %s",
        host,
        mb["port"],
        interval_s,
        base,
    )

    try:
        while True:
            try:
                raw = fetch_raw(cfg, log)
                if raw is not None:
                    payload = build_observation(raw, cfg, log)
                    if payload is not None:
                        station_id = payload["serial_number"]
                        topic = f"{base}/meteobridge-{station_id}/observation"
                        log.info("observation → %s", topic)
                        publish(client, cfg, topic, payload, log)
                        if ha_discovery:
                            publish_ha_discovery(station_id, client, cfg, log)
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
    parser = argparse.ArgumentParser(description="Meteobridge HTTP → MQTT datalogger")
    parser.add_argument(
        "--config",
        default="/opt/weatherdatalogger/config.ini",
        help="Path to config file (default: /opt/weatherdatalogger/config.ini)",
    )
    args = parser.parse_args()
    cfg = load_config(args.config)
    log_cfg = cfg["logging"]
    log = setup_logging(log_cfg["level"], log_cfg["file"])

    init_lightning(cfg, args.config, log)
    init_air_quality(cfg, args.config, log)
    run(cfg, args.config, log)


if __name__ == "__main__":
    main()
