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
import json
import logging
import socket
import sys
import time
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
    except KeyError, IndexError, TypeError:
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
    except KeyError, IndexError, TypeError:
        return None


def parse_evt_precip(msg: dict) -> dict | None:
    """Parse a precipitation-start event into a flat dict."""
    try:
        return {
            "timestamp": msg["evt"][0],
            "serial_number": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
        }
    except KeyError, IndexError, TypeError:
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
    except KeyError, IndexError, TypeError:
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
        default="config.ini",
        help="Path to config file (default: config.ini)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    log_cfg = cfg["logging"]
    log = setup_logging(log_cfg["level"], log_cfg["file"])

    run(cfg, log)


if __name__ == "__main__":
    main()
