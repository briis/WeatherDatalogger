#!/usr/bin/env python3
"""
WeatherDB Writer — MQTT to MariaDB persistence service.

Subscribes to MQTT observation topics published by the WeatherDatalogger
datalogger(s) and persists every reading to MariaDB:

  - realtime  — one row per station, upserted on every message
  - history   — full append-only time-series log for charting

Subscribes to:
    {base_topic}/+/observation

Stations are auto-registered in the stations table on first observation.

Usage:
    python3 db_writer.py [--config config.ini]
"""

import argparse
import configparser
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

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
# Helpers
# ---------------------------------------------------------------------------


def _parse_lightning_ts(value: str | None) -> datetime | None:
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
    lightning_ts = _parse_lightning_ts(payload.get("lightning_last_detected"))
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
    topic = f"{base}/+/observation"
    client.subscribe(topic, qos=0)
    log.info("MQTT connected — subscribed to %s", topic)


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

    # Derive station type from the topic segment: "tempest-ST-XXXXX" → "tempest"
    try:
        station_type = msg.topic.split("/")[1].split("-")[0]
    except IndexError:
        station_type = "unknown"

    log.debug("Message on %s", msg.topic)
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
