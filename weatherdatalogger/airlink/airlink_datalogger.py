#!/usr/bin/env python3
"""
Davis AirLink HTTP → MQTT Datalogger.

Polls the Davis AirLink local REST API and publishes air quality
observations to MQTT under the topic:

    weatherdatalogger/airlink-<device_id>/observation

Fields published (flat JSON object, SI units):
  PM1.0, PM2.5, PM10 (2-min average, 1h/3h/24h averages, NowCast)
  Temperature (°C), relative humidity (%), dew point (°C)
  AQI for PM2.5 and PM10 (US EPA, calculated from NowCast)
  PM data quality percentages

Usage:
    python3 airlink_datalogger.py [--config config.ini]
"""

import argparse
import configparser
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "airlink": {
        "enabled": "false",  # set true to enable this service
        "host": "",
        "port": "80",
        "interval_s": "60",
        "timeout_s": "10",
    },
    "mqtt": {
        "broker": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "tls": "false",
        "base_topic": "weatherdatalogger",
        "client_id": "airlink-datalogger",
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
    """Configure root logger and return the named 'airlink' logger."""
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
    return logging.getLogger("airlink")


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
# AQI calculation — US EPA breakpoints
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


# ---------------------------------------------------------------------------
# CAQI (Common Air Quality Index) — CITEAIR hourly breakpoints
# ---------------------------------------------------------------------------
# https://www.airqualitynow.eu (CITEAIR project). Computed from the current
# (hourly-equivalent) concentration rather than NowCast — CAQI is designed
# as a real-time hourly index, unlike the US AQI's 12h-smoothed NowCast
# convention. Official bands only go up to 100 ("Very High", open-ended);
# the last row here is an extrapolated continuation at the same
# index-per-µg/m³ slope as the High→Very High transition, so a genuinely
# smog-level reading still returns a number instead of None — real AirLink
# installs should essentially never reach it.
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


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------


def _f_to_c(fahrenheit: float | None) -> float | None:
    if fahrenheit is None:
        return None
    return round((fahrenheit - 32.0) * 5.0 / 9.0, 1)


# ---------------------------------------------------------------------------
# API fetch and parse
# ---------------------------------------------------------------------------


def fetch_observation(
    cfg: configparser.ConfigParser, log: logging.Logger
) -> dict | None:
    """Fetch current conditions from the AirLink local API; return a flat payload."""
    al = cfg["airlink"]
    host = al["host"].strip()
    port = int(al["port"])
    timeout = int(al["timeout_s"])
    url = f"http://{host}:{port}/v1/current_conditions"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read())
    except Exception:  # noqa: BLE001
        log.warning("AirLink API request failed (%s)", url)
        return None

    if body.get("error") is not None:
        log.warning("AirLink API error: %s", body["error"])
        return None

    data = body.get("data", {})
    conditions = data.get("conditions")
    if not conditions:
        log.warning("AirLink response has no conditions")
        return None

    cond = conditions[0]
    did: str = data.get("did", "unknown")
    ts = data.get("ts") or cond.get("last_report_time")

    now_pm25 = cond.get("pm_2p5_nowcast")
    now_pm10 = cond.get("pm_10_nowcast")
    cur_pm25 = cond.get("pm_2p5")
    cur_pm10 = cond.get("pm_10")

    return {
        "serial_number": did,
        "timestamp": ts,
        # PM1.0
        "pm_1_ugm3": cond.get("pm_1"),
        # PM2.5
        "pm_2p5_ugm3": cond.get("pm_2p5"),
        "pm_2p5_1h_ugm3": cond.get("pm_2p5_last_1_hour"),
        "pm_2p5_3h_ugm3": cond.get("pm_2p5_last_3_hours"),
        "pm_2p5_24h_ugm3": cond.get("pm_2p5_last_24_hours"),
        "pm_2p5_nowcast_ugm3": now_pm25,
        # PM10
        "pm_10_ugm3": cond.get("pm_10"),
        "pm_10_1h_ugm3": cond.get("pm_10_last_1_hour"),
        "pm_10_3h_ugm3": cond.get("pm_10_last_3_hours"),
        "pm_10_24h_ugm3": cond.get("pm_10_last_24_hours"),
        "pm_10_nowcast_ugm3": now_pm10,
        # AQI (US EPA, computed from NowCast concentration)
        "aqi_pm2p5": _aqi_pm2p5(now_pm25),
        "aqi_pm10": _aqi_pm10(now_pm10),
        # CAQI (EU CITEAIR, computed from current concentration)
        "caqi_pm2p5": _caqi_pm2p5(cur_pm25),
        "caqi_pm10": _caqi_pm10(cur_pm10),
        # Temperature & humidity (converted from °F to °C)
        "air_temperature_c": _f_to_c(cond.get("temp")),
        "relative_humidity_pct": cond.get("hum"),
        "dew_point_c": _f_to_c(cond.get("dew_point")),
        # PM data quality percentages
        "pct_pm_data_1h": cond.get("pct_pm_data_last_1_hour"),
        "pct_pm_data_3h": cond.get("pct_pm_data_last_3_hours"),
        "pct_pm_data_24h": cond.get("pct_pm_data_last_24_hours"),
        "pct_pm_data_nowcast": cond.get("pct_pm_data_nowcast"),
    }


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

_AIRLINK_SENSORS: list[tuple[str, str, str | None, str | None, str | None]] = [
    # PM particulate matter
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
    # Air Quality Index — US EPA
    ("aqi_pm2p5", "AQI (PM2.5)", None, "aqi", "measurement"),
    ("aqi_pm10", "AQI (PM10)", None, "aqi", "measurement"),
    # Air Quality Index — EU CAQI
    ("caqi_pm2p5", "CAQI (PM2.5)", None, "aqi", "measurement"),
    ("caqi_pm10", "CAQI (PM10)", None, "aqi", "measurement"),
    # Temperature & humidity
    ("air_temperature_c", "Temperature", "°C", "temperature", "measurement"),
    ("relative_humidity_pct", "Humidity", "%", "humidity", "measurement"),
    ("dew_point_c", "Dew Point", "°C", "temperature", "measurement"),
    # Data quality
    ("pct_pm_data_1h", "PM Data Quality (1h)", "%", None, "measurement"),
    ("pct_pm_data_nowcast", "PM Data Quality (NowCast)", "%", None, "measurement"),
]

# Icon overrides for sensors with no matching HA device class (and thus no
# built-in icon).
_SENSOR_ICON_OVERRIDES = {
    "pct_pm_data_1h": "mdi:percent",
    "pct_pm_data_nowcast": "mdi:percent",
}

_discovered: set[str] = set()


def _device_info(did: str) -> dict:
    return {
        "identifiers": [f"airlink_{did}"],
        "name": f"AirLink {did}",
        "manufacturer": "Davis Instruments",
        "model": "AirLink",
    }


def publish_ha_discovery(
    did: str,
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    log: logging.Logger,
) -> None:
    """Publish retained MQTT discovery config for all AirLink sensors (once per run)."""
    if did in _discovered:
        return

    prefix = cfg["homeassistant"]["discovery_prefix"].rstrip("/")
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    state_topic = f"{base}/airlink-{did}/observation"
    device = _device_info(did)

    for field, name, unit, device_class, state_class in _AIRLINK_SENSORS:
        unique_id = f"airlink_{did}_{field}"
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

    _discovered.add(did)
    log.info(
        "HA discovery published: AirLink %s (%d sensors)", did, len(_AIRLINK_SENSORS)
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, config_path: str, log: logging.Logger) -> None:
    """Connect to MQTT, then poll the AirLink API on a fixed interval."""
    al = cfg["airlink"]
    if not al.getboolean("enabled"):
        if not _enabled_key_present(config_path, "airlink"):
            log.warning(
                "[airlink] enabled is not set in config.ini — defaulting to "
                "disabled as of this version (previously ran whenever `host` "
                "was set). Add 'enabled = true' under [airlink] to keep "
                "logging AirLink data."
            )
        else:
            log.info("[airlink] enabled = false — exiting")
        return

    client = make_mqtt_client(cfg, log)
    mqtt_connect(client, cfg, log)
    client.loop_start()

    host = al["host"].strip()
    if not host:
        log.error(
            "AirLink host is not configured. "
            "Set [airlink] host in config.ini and restart."
        )
        client.loop_stop()
        client.disconnect()
        return

    interval_s = int(al["interval_s"])
    base = cfg["mqtt"]["base_topic"].rstrip("/")
    ha_discovery = cfg["homeassistant"].getboolean("discovery")

    log.info(
        "Polling AirLink at %s:%s every %s s  base topic: %s",
        host,
        al["port"],
        interval_s,
        base,
    )

    try:
        while True:
            try:
                payload = fetch_observation(cfg, log)
                if payload is not None:
                    did = payload["serial_number"]
                    topic = f"{base}/airlink-{did}/observation"
                    log.info("observation → %s", topic)
                    publish(client, cfg, topic, payload, log)
                    if ha_discovery:
                        publish_ha_discovery(did, client, cfg, log)
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
    parser = argparse.ArgumentParser(description="Davis AirLink HTTP → MQTT datalogger")
    parser.add_argument(
        "--config",
        default="/opt/weatherdatalogger/config.ini",
        help="Path to config file (default: /opt/weatherdatalogger/config.ini)",
    )
    args = parser.parse_args()
    cfg = load_config(args.config)
    log_cfg = cfg["logging"]
    log = setup_logging(log_cfg["level"], log_cfg["file"])
    run(cfg, args.config, log)


if __name__ == "__main__":
    main()
