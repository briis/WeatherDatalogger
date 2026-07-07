#!/usr/bin/env python3
"""
WeatherDB Writer — MQTT to MariaDB persistence service.

Subscribes to MQTT observation topics published by the WeatherDatalogger
datalogger(s) and persists every reading to MariaDB:

  - realtime  — one row per station, upserted on every message
  - history   — full append-only time-series log for charting

Also subscribes to visualcrossing_datalogger.py's forecast topics and
persists the latest Visual Crossing fetch (not an append-only history) to:

  - forecast_current — one row per location, upserted on every fetch
  - forecast_hourly  — one row per (location, forecast_time)
  - forecast_daily   — one row per (location, forecast_time)

Subscribes to:
    {base_topic}/+/observation
    {base_topic}/forecast-+/+

Stations are auto-registered in the stations table on first observation.

Usage:
    python3 db_writer.py [--config config.ini]
"""

import argparse
import configparser
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import paho.mqtt.client as mqtt
import pymysql
import pymysql.cursors

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "mqtt": {
        "broker": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "tls": "false",
        "base_topic": "weatherdatalogger",
        "client_id": "weatherdb-writer",
    },
    "database": {
        "host": "localhost",
        "port": "3306",
        "name": "weatherdatalogger",
        "user": "weatherlogger",
        "password": "",
    },
    "logging": {
        "level": "INFO",
        "file": "",
    },
}

# ---------------------------------------------------------------------------
# Observation field mapping
# ---------------------------------------------------------------------------
# Fields that map 1:1 from the MQTT payload to DB columns.
# station_id (from serial_number), recorded_at (from timestamp), and
# lightning_last_detected (ISO string → DATETIME) are handled separately.
_OBS_FIELDS: tuple[str, ...] = (
    "wind_lull_ms",
    "wind_avg_ms",
    "wind_gust_ms",
    "wind_direction_deg",
    "wind_beaufort",
    "wind_beaufort_description",
    "station_pressure_mb",
    "sea_level_pressure_mb",
    "pressure_trend_mb",
    "pressure_trend",
    "sea_level_pressure_trend_mb",
    "sea_level_pressure_trend",
    "air_temperature_c",
    "relative_humidity_pct",
    "dew_point_c",
    "wet_bulb_c",
    "delta_t_c",
    "feels_like_c",
    "heat_index_c",
    "wind_chill_c",
    "illuminance_lux",
    "uv_index",
    "solar_radiation_wm2",
    "rain_accumulation_mm",
    "rain_rate_mmh",
    "lightning_count_3h",
    "lightning_min_dist_3h_km",
    "lightning_max_dist_3h_km",
    "vapor_pressure_mb",
    "air_density_kgm3",
    "battery_volts",
    "battery_low",
    # Indoor — Davis receiver's own BME280, co-located with the ESP32/CC1101,
    # not the outdoor ISS (NULL for other station types)
    "indoor_temperature_c",
    "indoor_humidity_pct",
    # Air quality — Davis AirLink (NULL for other station types)
    "pm_1_ugm3",
    "pm_2p5_ugm3",
    "pm_2p5_1h_ugm3",
    "pm_2p5_3h_ugm3",
    "pm_2p5_24h_ugm3",
    "pm_2p5_nowcast_ugm3",
    "pm_10_ugm3",
    "pm_10_1h_ugm3",
    "pm_10_3h_ugm3",
    "pm_10_24h_ugm3",
    "pm_10_nowcast_ugm3",
    "aqi_pm2p5",
    "aqi_pm10",
    "caqi_pm2p5",
    "caqi_pm10",
)

_ALL_COLS: tuple[str, ...] = (*_OBS_FIELDS, "lightning_last_detected")
_COL_LIST = ", ".join(_ALL_COLS)
_PLACEHOLDERS = ", ".join(["%s"] * len(_ALL_COLS))
_UPDATE_CLAUSE = ", ".join(f"{c} = VALUES({c})" for c in _ALL_COLS)

_SQL_UPSERT_REALTIME = (
    f"INSERT INTO realtime (station_id, recorded_at, {_COL_LIST}) "
    f"VALUES (%s, %s, {_PLACEHOLDERS}) "
    f"ON DUPLICATE KEY UPDATE recorded_at = VALUES(recorded_at), {_UPDATE_CLAUSE}"
)

_SQL_INSERT_HISTORY = (
    f"INSERT INTO history (station_id, recorded_at, {_COL_LIST}) "
    f"VALUES (%s, %s, {_PLACEHOLDERS})"
)

_SQL_ENSURE_STATION = (
    "INSERT IGNORE INTO stations (station_id, station_type) VALUES (%s, %s)"
)

# ---------------------------------------------------------------------------
# Forecast field mapping
# ---------------------------------------------------------------------------
# visualcrossing_datalogger.py's forecast payloads use Home Assistant's own
# weather attribute names (condition/temperature/humidity/...) rather than
# this project's usual descriptive-snake_case-with-unit-suffix convention
# (see db/README.md), so each JSON key is mapped explicitly to its DB column
# rather than reusing it outright, unlike _OBS_FIELDS above.
_FORECAST_CURRENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("condition", "weather_condition"),
    ("temperature", "temperature_c"),
    ("feels_like", "feels_like_c"),
    ("humidity", "humidity_pct"),
    ("dew_point", "dew_point_c"),
    ("wind_speed", "wind_speed_ms"),
    ("wind_gust_speed", "wind_gust_ms"),
    ("wind_bearing", "wind_bearing_deg"),
    ("pressure", "pressure_mb"),
    ("cloud_cover", "cloud_cover_pct"),
    ("uv_index", "uv_index"),
    ("visibility", "visibility_km"),
    ("solar_radiation", "solar_radiation_wm2"),
)
_FORECAST_HOURLY_FIELDS: tuple[tuple[str, str], ...] = (
    ("condition", "weather_condition"),
    ("temperature", "temperature_c"),
    ("feels_like", "feels_like_c"),
    ("humidity", "humidity_pct"),
    ("dew_point", "dew_point_c"),
    ("wind_speed", "wind_speed_ms"),
    ("wind_gust_speed", "wind_gust_ms"),
    ("wind_bearing", "wind_bearing_deg"),
    ("pressure", "pressure_mb"),
    ("cloud_cover", "cloud_cover_pct"),
    ("uv_index", "uv_index"),
    ("precipitation", "precipitation_mm"),
    ("precipitation_probability", "precipitation_probability_pct"),
)
_FORECAST_DAILY_FIELDS: tuple[tuple[str, str], ...] = (
    ("condition", "weather_condition"),
    ("temperature", "temperature_high_c"),
    ("templow", "temperature_low_c"),
    ("feels_like", "feels_like_c"),
    ("humidity", "humidity_pct"),
    ("dew_point", "dew_point_c"),
    ("wind_speed", "wind_speed_ms"),
    ("wind_gust_speed", "wind_gust_ms"),
    ("wind_bearing", "wind_bearing_deg"),
    ("pressure", "pressure_mb"),
    ("cloud_cover", "cloud_cover_pct"),
    ("uv_index", "uv_index"),
    ("precipitation", "precipitation_mm"),
    ("precipitation_probability", "precipitation_probability_pct"),
)

_FC_CURRENT_COLS = ", ".join(c for _, c in _FORECAST_CURRENT_FIELDS)
_SQL_UPSERT_FORECAST_CURRENT = (
    f"INSERT INTO forecast_current (location, fetched_at, {_FC_CURRENT_COLS}) "
    f"VALUES (%s, %s, {', '.join(['%s'] * len(_FORECAST_CURRENT_FIELDS))}) "
    "ON DUPLICATE KEY UPDATE fetched_at = VALUES(fetched_at), "
    + ", ".join(f"{c} = VALUES({c})" for _, c in _FORECAST_CURRENT_FIELDS)
)

_FC_HOURLY_COLS = ", ".join(c for _, c in _FORECAST_HOURLY_FIELDS)
_SQL_UPSERT_FORECAST_HOURLY = (
    "INSERT INTO forecast_hourly "
    f"(location, forecast_time, fetched_at, {_FC_HOURLY_COLS}) "
    f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(_FORECAST_HOURLY_FIELDS))}) "
    "ON DUPLICATE KEY UPDATE fetched_at = VALUES(fetched_at), "
    + ", ".join(f"{c} = VALUES({c})" for _, c in _FORECAST_HOURLY_FIELDS)
)
_SQL_DELETE_STALE_FORECAST_HOURLY = (
    "DELETE FROM forecast_hourly WHERE location = %s AND forecast_time NOT IN %s"
)

_FC_DAILY_COLS = ", ".join(c for _, c in _FORECAST_DAILY_FIELDS)
_SQL_UPSERT_FORECAST_DAILY = (
    "INSERT INTO forecast_daily "
    f"(location, forecast_time, fetched_at, {_FC_DAILY_COLS}) "
    f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(_FORECAST_DAILY_FIELDS))}) "
    "ON DUPLICATE KEY UPDATE fetched_at = VALUES(fetched_at), "
    + ", ".join(f"{c} = VALUES({c})" for _, c in _FORECAST_DAILY_FIELDS)
)
_SQL_DELETE_STALE_FORECAST_DAILY = (
    "DELETE FROM forecast_daily WHERE location = %s AND forecast_time NOT IN %s"
)


class _ForecastSeriesSpec(NamedTuple):
    """Per-table bits _write_forecast_series needs, bundled into one argument."""

    table: str
    upsert_sql: str
    delete_stale_sql: str
    fields: tuple[tuple[str, str], ...]


_HOURLY_SPEC = _ForecastSeriesSpec(
    "forecast_hourly",
    _SQL_UPSERT_FORECAST_HOURLY,
    _SQL_DELETE_STALE_FORECAST_HOURLY,
    _FORECAST_HOURLY_FIELDS,
)
_DAILY_SPEC = _ForecastSeriesSpec(
    "forecast_daily",
    _SQL_UPSERT_FORECAST_DAILY,
    _SQL_DELETE_STALE_FORECAST_DAILY,
    _FORECAST_DAILY_FIELDS,
)

# rain_raw_log — temporary table for the raw RF tip-counter rain value
# (davis_rain_raw), logged alongside the Meteobridge-corrected figure in
# history.rain_accumulation_mm for accuracy comparison. No FK to `stations`:
# unlike /observation, this can arrive before a station is registered.
# raw_tip_count is the unfiltered 0-127 counter straight off the packet;
# rain_raw_mm is the on-device delta math's derived total — both are stored
# so the math can be checked against the raw counter, not just trusted.
_SQL_INSERT_RAIN_RAW = (
    "INSERT INTO rain_raw_log (station_id, recorded_at, raw_tip_count, rain_raw_mm) "
    "VALUES (%s, %s, %s, %s)"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _payload_to_row(payload: dict) -> tuple[str, datetime, tuple]:
    """Return (station_id, recorded_at, column_values) from an observation payload."""
    station_id: str = payload["serial_number"]
    recorded_at = datetime.fromtimestamp(payload["timestamp"], tz=UTC).replace(
        tzinfo=None
    )
    field_values = tuple(payload.get(f) for f in _OBS_FIELDS)
    lightning_ts = _parse_iso_utc(payload.get("lightning_last_detected"))
    return station_id, recorded_at, (*field_values, lightning_ts)


# ---------------------------------------------------------------------------
# Database writer
# ---------------------------------------------------------------------------


class DbWriter:
    """Manages the MariaDB connection and writes observation data."""

    def __init__(self, cfg: configparser.ConfigParser, log: logging.Logger) -> None:
        self._cfg = cfg
        self._log = log
        self._conn: pymysql.connections.Connection | None = None
        self._known_stations: set[str] = set()
        self._connect()

    def _connect(self) -> None:
        d = self._cfg["database"]
        self._conn = pymysql.connect(
            host=d["host"],
            port=int(d["port"]),
            database=d["name"],
            user=d["user"],
            password=d["password"],
            autocommit=True,
            charset="utf8mb4",
        )
        self._log.info("Connected to MariaDB at %s/%s", d["host"], d["name"])

    def _execute(self, sql: str, args: tuple) -> None:
        """Execute one statement, reconnecting once if the connection was lost."""
        for attempt in range(2):
            try:
                with self._conn.cursor() as cur:  # type: ignore[union-attr]
                    cur.execute(sql, args)
                return
            except (pymysql.OperationalError, pymysql.InterfaceError):
                if attempt == 0:
                    self._log.warning("DB connection lost — reconnecting…")
                    self._connect()
                else:
                    raise

    def ensure_station(self, station_id: str, station_type: str) -> None:
        if station_id in self._known_stations:
            return
        self._execute(_SQL_ENSURE_STATION, (station_id, station_type))
        self._known_stations.add(station_id)
        self._log.info("Registered station: %s (%s)", station_id, station_type)

    def write_observation(self, payload: dict, station_type: str = "tempest") -> None:
        try:
            station_id, recorded_at, values = _payload_to_row(payload)
        except (KeyError, TypeError, ValueError) as exc:
            self._log.warning("Skipping malformed observation payload: %s", exc)
            return

        self.ensure_station(station_id, station_type)

        row = (station_id, recorded_at, *values)
        try:
            self._execute(_SQL_UPSERT_REALTIME, row)
            self._execute(_SQL_INSERT_HISTORY, row)
            self._log.debug("Wrote %s @ %s", station_id, recorded_at)
        except pymysql.Error as exc:
            self._log.error("DB write error for %s: %s", station_id, exc)

    def write_rain_raw(self, station_id: str, payload: dict) -> None:
        try:
            raw_tip_count = int(payload["raw_tip_count"])
            rain_raw_mm = float(payload["rain_raw_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            self._log.warning("Skipping malformed rain_raw payload: %s", exc)
            return

        # Davis (ESPHome) has no hardware clock — stamp with arrival time,
        # same as the fallback used for /observation in _on_message below.
        recorded_at = datetime.now(UTC).replace(tzinfo=None)
        row = (station_id, recorded_at, raw_tip_count, rain_raw_mm)
        try:
            self._execute(_SQL_INSERT_RAIN_RAW, row)
            self._log.debug(
                "Wrote rain_raw %s @ %s: raw_tip_count=%d rain_raw_mm=%.1f",
                station_id,
                recorded_at,
                raw_tip_count,
                rain_raw_mm,
            )
        except pymysql.Error as exc:
            self._log.error("DB write error for rain_raw %s: %s", station_id, exc)

    def write_forecast_current(self, location: str, payload: dict) -> None:
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        values = tuple(payload.get(f) for f, _ in _FORECAST_CURRENT_FIELDS)
        row = (location, fetched_at, *values)
        try:
            self._execute(_SQL_UPSERT_FORECAST_CURRENT, row)
            self._log.debug("Wrote forecast_current for %s @ %s", location, fetched_at)
        except pymysql.Error as exc:
            self._log.error("DB write error for forecast_current %s: %s", location, exc)

    def _write_forecast_series(
        self, spec: _ForecastSeriesSpec, location: str, payload: list[dict]
    ) -> None:
        if not isinstance(payload, list) or not payload:
            self._log.warning(
                "Skipping empty/malformed %s payload for %s", spec.table, location
            )
            return

        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        forecast_times: list[datetime] = []
        try:
            for entry in payload:
                ts = _parse_iso_utc(entry.get("datetime"))
                if ts is None:
                    continue
                forecast_times.append(ts)
                values = tuple(entry.get(f) for f, _ in spec.fields)
                self._execute(spec.upsert_sql, (location, ts, fetched_at, *values))
            if forecast_times:
                self._execute(spec.delete_stale_sql, (location, tuple(forecast_times)))
            self._log.debug(
                "Wrote %s for %s @ %s (%d entries)",
                spec.table,
                location,
                fetched_at,
                len(forecast_times),
            )
        except pymysql.Error as exc:
            self._log.error("DB write error for %s %s: %s", spec.table, location, exc)

    def write_forecast_hourly(self, location: str, payload: list[dict]) -> None:
        self._write_forecast_series(_HOURLY_SPEC, location, payload)

    def write_forecast_daily(self, location: str, payload: list[dict]) -> None:
        self._write_forecast_series(_DAILY_SPEC, location, payload)


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------


def _on_connect(
    client: mqtt.Client,
    userdata: dict,
    _flags: dict,
    rc: int,
) -> None:
    log: logging.Logger = userdata["log"]
    cfg: configparser.ConfigParser = userdata["cfg"]
    if rc != 0:
        log.error("MQTT connect failed with rc=%s", rc)
        return
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    client.subscribe(f"{base}/+/observation", qos=0)
    # rain_raw capture is disabled for now — the Davis firmware no longer
    # publishes that topic either, now that davis_rain/davis_rain_rate are
    # computed standalone from the RF tip counter. To resume a future
    # comparison exercise, subscribe to f"{base}/+/rain_raw" here and route
    # it to DbWriter.write_rain_raw() in _on_message below.
    # Forecast — tempest_datalogger.py's forecast thread publishes to
    # forecast-<location>/{current,forecast_hourly,forecast_daily}, a
    # separate segment prefix from station observation topics above.
    client.subscribe(f"{base}/forecast-+/+", qos=0)
    log.info(
        "MQTT connected — subscribed to %s/+/observation and %s/forecast-+/+",
        base,
        base,
    )


def _on_disconnect(
    _client: mqtt.Client,
    userdata: dict,
    rc: int,
) -> None:
    userdata["log"].warning("MQTT disconnected (rc=%s) — will reconnect", rc)


def _on_message(
    _client: mqtt.Client,
    userdata: dict,
    msg: mqtt.MQTTMessage,
) -> None:
    log: logging.Logger = userdata["log"]
    writer: DbWriter = userdata["writer"]

    try:
        payload = json.loads(msg.payload)
    except json.JSONDecodeError:
        log.warning("Non-JSON message on %s — ignored", msg.topic)
        return

    # Derive station segment from the topic:
    # "weatherdatalogger/tempest-ST-XXXXX/observation" → "tempest-ST-XXXXX"
    topic_parts = msg.topic.split("/")
    try:
        station_segment = topic_parts[1]
        subtopic = topic_parts[2]
        station_type = station_segment.split("-")[0]
    except IndexError:
        station_segment = "unknown"
        subtopic = "unknown"
        station_type = "unknown"

    log.debug("Message on %s", msg.topic)

    # Forecast — "forecast-<location>/{current,forecast_hourly,forecast_daily}",
    # a different shape from station observations (no station_id/stations
    # row involved) — dispatch separately rather than falling into the
    # Davis-fallback/write_observation path below.
    if station_segment.startswith("forecast-"):
        location = station_segment[len("forecast-") :]
        if subtopic == "current":
            writer.write_forecast_current(location, payload)
        elif subtopic == "forecast_hourly":
            writer.write_forecast_hourly(location, payload)
        elif subtopic == "forecast_daily":
            writer.write_forecast_daily(location, payload)
        else:
            log.debug("Ignoring unrecognized forecast subtopic: %s", msg.topic)
        return

    # Davis (ESPHome) has no hardware serial or clock sync, unlike the
    # Tempest/AirLink Python dataloggers — fall back to the topic segment
    # and message-arrival time so its observations aren't dropped as malformed.
    payload.setdefault("serial_number", station_segment)
    payload.setdefault("timestamp", int(time.time()))

    writer.write_observation(payload, station_type)


def _make_mqtt_client(
    cfg: configparser.ConfigParser,
    log: logging.Logger,
    writer: DbWriter,
) -> mqtt.Client:
    m = cfg["mqtt"]
    client = mqtt.Client(client_id=m["client_id"], clean_session=True)
    client.user_data_set({"cfg": cfg, "log": log, "writer": writer})
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message

    if m["username"]:
        client.username_pw_set(m["username"], m["password"] or None)

    if m.getboolean("tls"):
        client.tls_set()

    return client


# ---------------------------------------------------------------------------
# Config / logging
# ---------------------------------------------------------------------------


def load_config(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFAULT_CONFIG)
    if path.exists():
        cfg.read(path)
    else:
        sys.exit(f"Config file not found: {path}")
    return cfg


def setup_logging(cfg: configparser.ConfigParser) -> logging.Logger:
    level = getattr(logging, cfg["logging"]["level"].upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = cfg["logging"]["file"].strip()
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return logging.getLogger("weatherdb")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    writer = DbWriter(cfg, log)

    client = _make_mqtt_client(cfg, log, writer)
    m = cfg["mqtt"]
    client.connect(m["broker"], int(m["port"]), keepalive=60)

    log.info(
        "Connecting to MQTT broker %s:%s  base topic: %s",
        m["broker"],
        m["port"],
        m["base_topic"],
    )
    client.loop_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="WeatherDB Writer")
    parser.add_argument(
        "--config",
        default=Path("/opt/weatherdatalogger/config.ini"),
        type=Path,
        metavar="PATH",
    )
    args = parser.parse_args()
    cfg = load_config(args.config)
    log = setup_logging(cfg)
    run(cfg, log)


if __name__ == "__main__":
    main()
