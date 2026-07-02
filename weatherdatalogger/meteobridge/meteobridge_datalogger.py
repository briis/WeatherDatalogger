#!/usr/bin/env python3
"""
Meteobridge → Davis Rain Corrector.

Polls a Meteobridge Pro's local REST template API for the Davis Vantage
Vue's rain readings and republishes them as MQTT corrections to the
davis-vantage-receiver ESPHome device's own control topics:

    weatherdatalogger/davis-vantage-receiver/set_daily_rain
    weatherdatalogger/davis-vantage-receiver/set_rain_rate

Meteobridge is wired directly to the same Vantage Vue ISS and has proven
consistent with the physical console, whereas the CC1101 RF receiver's own
rain rate needs to see two tips after every reboot before it can compute a
value (see davis/AGENT.md "Rain accumulation & rate"). This service acts as
a periodic correction source rather than a full independent station — it
does not publish its own observation topic or get its own row in the
database; it only nudges the existing Davis entities toward Meteobridge's
more trustworthy reading.

Units: the template below requests plain numeric output and assumes
Meteobridge is configured for metric units (mm / mm per hour), consistent
with the rest of this project. If your Meteobridge is configured for
imperial units, either reconfigure it to metric or adjust MM_TEMPLATE below.

Usage:
    python3 meteobridge_datalogger.py [--config config.ini]
"""

import argparse
import configparser
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "meteobridge": {
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
        "client_id": "meteobridge-datalogger",
        "qos": "0",
    },
    "logging": {
        "level": "INFO",
        "file": "",
    },
}

# Meteobridge template — square-bracket macros are substituted server-side
# before the response is sent. Double-quoted keys and unquoted numeric
# placeholders produce a response that's already valid JSON, so no custom
# parsing is needed on our end.
MM_TEMPLATE = '{"rain_today":[rain0total-act],"rain_rate":[rain0rate-act]}'

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(level_str: str, log_file: str) -> logging.Logger:
    """Configure root logger and return the named 'meteobridge' logger."""
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


# ---------------------------------------------------------------------------
# API fetch and parse
# ---------------------------------------------------------------------------


def fetch_rain(
    cfg: configparser.ConfigParser, log: logging.Logger
) -> tuple[float, float] | None:
    """Fetch (rain_today_mm, rain_rate_mmh) from Meteobridge; None on any failure."""
    mb = cfg["meteobridge"]
    host = mb["host"].strip()
    port = int(mb["port"])
    timeout = int(mb["timeout_s"])
    query = urllib.parse.urlencode({"template": MM_TEMPLATE})
    url = f"http://{host}:{port}/cgi-bin/template.cgi?{query}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            body = resp.read()
    except Exception:  # noqa: BLE001
        log.warning("Meteobridge request failed (%s)", url)
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        log.warning("Meteobridge response was not valid JSON: %r", body[:200])
        return None

    rain_today = data.get("rain_today")
    rain_rate = data.get("rain_rate")
    if rain_today is None or rain_rate is None:
        log.warning("Meteobridge response missing expected fields: %s", data)
        return None

    try:
        return float(rain_today), float(rain_rate)
    except (TypeError, ValueError):
        log.warning("Meteobridge returned non-numeric values: %s", data)
        return None


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


def publish_correction(
    client: mqtt.Client,
    cfg: configparser.ConfigParser,
    topic: str,
    value: float,
    log: logging.Logger,
) -> None:
    """Publish a bare numeric payload — the Davis control topics expect a plain
    mm/mm-per-hour value, not JSON. Never retained: these are one-shot
    corrections, not state to replay to a freshly (re)connecting subscriber.
    """
    qos = int(cfg["mqtt"]["qos"])
    payload = f"{value:.1f}"
    try:
        result = client.publish(topic, payload, qos=qos, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("MQTT publish error rc=%s topic=%s", result.rc, topic)
        else:
            log.debug("Published %s → %s", payload, topic)
    except Exception:
        log.exception("Publish exception")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    """Connect to MQTT, then poll Meteobridge on a fixed interval."""
    client = make_mqtt_client(cfg, log)
    mqtt_connect(client, cfg, log)
    client.loop_start()

    mb = cfg["meteobridge"]
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
    rain_total_topic = f"{base}/davis-vantage-receiver/set_daily_rain"
    rain_rate_topic = f"{base}/davis-vantage-receiver/set_rain_rate"

    log.info(
        "Polling Meteobridge at %s:%s every %s s  →  %s / %s",
        host,
        mb["port"],
        interval_s,
        rain_total_topic,
        rain_rate_topic,
    )

    try:
        while True:
            try:
                result = fetch_rain(cfg, log)
                if result is not None:
                    rain_today, rain_rate = result
                    log.info(
                        "Meteobridge: rain_today=%.1fmm rain_rate=%.1fmm/h",
                        rain_today,
                        rain_rate,
                    )
                    publish_correction(client, cfg, rain_total_topic, rain_today, log)
                    publish_correction(client, cfg, rain_rate_topic, rain_rate, log)
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
    parser = argparse.ArgumentParser(description="Meteobridge → Davis rain corrector")
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
