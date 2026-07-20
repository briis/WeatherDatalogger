#!/usr/bin/env bash
# set_daily_rain.sh — Manually correct the Davis receiver's daily rain total
# by publishing to its MQTT correction topic (see the `mqtt: on_message:`
# block in davisnet-weatherlogger.yaml). Useful after a reflash/reboot that
# landed between tips and lost sync with the physical tip counter, or if the
# running total has simply drifted from the console's own reading — read the
# correct value off the console and pass it here.
#
# Usage:
#   set_daily_rain.sh <mm>
#
# Example:
#   set_daily_rain.sh 5.4
#
# Reads MQTT broker settings from the shared config file (default
# /opt/weatherdatalogger/config.ini — override with the CONFIG_INI env var).
# Requires mosquitto_pub (mosquitto-clients package).

set -euo pipefail

CONFIG_INI="${CONFIG_INI:-/opt/weatherdatalogger/config.ini}"
# Must match the `device:` substitution in davisnet-weatherlogger.yaml — the
# control topic uses the device's static name, not the dynamic
# weatherdatalogger/davis-<id> observation prefix (the transmitter ID
# auto-locks at runtime and isn't known ahead of time). If your unit still
# runs the superseded davis-vantage-receiver.yaml, change this back to
# "davis-vantage-receiver".
DEVICE_TOPIC_SEGMENT="davisnet-datalogger"
FIRMWARE_MAX_MM=500 # must match the clamp in the yaml's on_message handler

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <daily_rain_mm>" >&2
    echo "Example: $0 5.4" >&2
    exit 1
fi

VALUE="$1"

if ! [[ "$VALUE" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "Error: '$VALUE' is not a non-negative number (mm)." >&2
    exit 1
fi

if awk "BEGIN { exit !($VALUE >= $FIRMWARE_MAX_MM) }"; then
    echo "Error: $VALUE mm is >= the firmware's ${FIRMWARE_MAX_MM}mm sanity clamp — it would be rejected on-device." >&2
    exit 1
fi

if [[ ! -f "$CONFIG_INI" ]]; then
    echo "Error: config file not found: $CONFIG_INI" >&2
    echo "Set CONFIG_INI=/path/to/config.ini to override." >&2
    exit 1
fi

if ! command -v mosquitto_pub >/dev/null 2>&1; then
    echo "Error: mosquitto_pub not found. Install the mosquitto-clients package." >&2
    exit 1
fi

# Pull MQTT settings out of the shared config — same configparser-via-heredoc
# pattern deploy.sh uses to generate db.cnf, more robust than hand-parsing
# INI in bash.
eval "$(python3 - "$CONFIG_INI" <<'PYEOF'
import configparser, shlex, sys

c = configparser.ConfigParser()
c.read(sys.argv[1])


def get(key, default=""):
    return c.get("mqtt", key, fallback=default)


def out(key, val):
    print(f"{key}={shlex.quote(str(val))}")


out("MQTT_BROKER", get("broker", "localhost"))
out("MQTT_PORT", get("port", "1883"))
out("MQTT_USERNAME", get("username", ""))
out("MQTT_PASSWORD", get("password", ""))
out("MQTT_TLS", "true" if c.getboolean("mqtt", "tls", fallback=False) else "false")
out("MQTT_BASE_TOPIC", get("base_topic", "weatherdatalogger"))
PYEOF
)"

TOPIC="${MQTT_BASE_TOPIC}/${DEVICE_TOPIC_SEGMENT}/set_daily_rain"

ARGS=(-h "$MQTT_BROKER" -p "$MQTT_PORT" -t "$TOPIC" -m "$VALUE")
[[ -n "$MQTT_USERNAME" ]] && ARGS+=(-u "$MQTT_USERNAME")
[[ -n "$MQTT_PASSWORD" ]] && ARGS+=(-P "$MQTT_PASSWORD")
[[ "$MQTT_TLS" == "true" ]] && ARGS+=(--capath /etc/ssl/certs)

echo "==> Publishing daily rain correction: ${VALUE} mm -> ${TOPIC} (broker ${MQTT_BROKER}:${MQTT_PORT})"
mosquitto_pub "${ARGS[@]}"
echo "==> Sent. Check 'esphome logs ESPHome/davis/davisnet-weatherlogger.yaml' or the Home Assistant entity to confirm it was accepted."
