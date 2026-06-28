#!/usr/bin/env python3
"""Send simulated WeatherFlow Tempest UDP broadcasts to localhost:50222.

Usage:
    python3 scripts/simulate_udp.py [--host HOST] [--port PORT] [--count N] [--interval SECS]

Sends one packet of every Tempest message type, then loops (if --count > 1).
"""

import argparse
import json
import random
import socket
import time

HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 50222

SERIAL = "ST-00012345"
HUB_SN = "HB-00012345"


def _ts() -> int:
    return int(time.time())


def make_obs_st() -> dict:
    return {
        "serial_number": SERIAL,
        "type": "obs_st",
        "hub_sn": HUB_SN,
        "obs": [[
            _ts(),
            round(random.uniform(0.0, 1.5), 2),   # wind_lull
            round(random.uniform(1.0, 4.0), 2),   # wind_avg
            round(random.uniform(3.0, 8.0), 2),   # wind_gust
            random.randint(0, 359),                # wind_dir
            3,                                     # sample_interval
            round(random.uniform(1010.0, 1025.0), 1),  # pressure
            round(random.uniform(15.0, 25.0), 1),      # temp_c
            random.randint(40, 80),                    # humidity
            random.randint(5000, 80000),               # illuminance
            round(random.uniform(0.0, 6.0), 1),        # uv
            random.randint(100, 900),                  # solar_radiation
            0.0,                                       # rain_accum
            0,                                         # precip_type
            random.randint(5, 40),                     # lightning_dist
            0,                                         # lightning_count
            round(random.uniform(2.50, 2.80), 2),      # battery
            1,                                         # report_interval_min
        ]],
        "firmware_revision": 171,
    }


def make_rapid_wind() -> dict:
    return {
        "serial_number": SERIAL,
        "type": "rapid_wind",
        "hub_sn": HUB_SN,
        "ob": [_ts(), round(random.uniform(0.5, 6.0), 2), random.randint(0, 359)],
    }


def make_evt_precip() -> dict:
    return {
        "serial_number": SERIAL,
        "type": "evt_precip",
        "hub_sn": HUB_SN,
        "evt": [_ts()],
    }


def make_evt_strike() -> dict:
    return {
        "serial_number": SERIAL,
        "type": "evt_strike",
        "hub_sn": HUB_SN,
        "evt": [_ts(), random.randint(5, 40), random.randint(1000, 50000)],
    }


def make_device_status() -> dict:
    return {
        "serial_number": SERIAL,
        "type": "device_status",
        "hub_sn": HUB_SN,
        "timestamp": _ts(),
        "uptime": random.randint(3600, 86400),
        "voltage": round(random.uniform(2.50, 2.80), 2),
        "firmware_revision": 171,
        "rssi": random.randint(-70, -40),
        "hub_rssi": random.randint(-70, -40),
        "sensor_status": 0,
        "debug": 0,
    }


def make_hub_status() -> dict:
    return {
        "serial_number": HUB_SN,
        "type": "hub_status",
        "firmware_revision": "171",
        "uptime": random.randint(3600, 86400),
        "rssi": random.randint(-70, -40),
        "timestamp": _ts(),
        "reset_flags": "BOR,PIN,POR",
        "seq": random.randint(1, 9999),
        "radio_stats": [25, 1, 0, 3, 0],
        "mqtt_stats": [1, 1],
    }


MESSAGES = [
    make_obs_st,
    make_rapid_wind,
    make_evt_precip,
    make_evt_strike,
    make_device_status,
    make_hub_status,
]


def send_all(sock: socket.socket, host: str, port: int) -> None:
    for factory in MESSAGES:
        msg = factory()
        payload = json.dumps(msg).encode()
        sock.sendto(payload, (host, port))
        print(f"  sent {msg['type']!r}  ({len(payload)} bytes)")


def main() -> None:
    p = argparse.ArgumentParser(description="Simulate Tempest UDP broadcasts")
    p.add_argument("--host", default=HOST_DEFAULT)
    p.add_argument("--port", type=int, default=PORT_DEFAULT)
    p.add_argument("--count", type=int, default=1, help="0 = loop forever")
    p.add_argument("--interval", type=float, default=3.0, help="seconds between rounds")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    iteration = 0
    try:
        while args.count == 0 or iteration < args.count:
            iteration += 1
            print(f"[round {iteration}]")
            send_all(sock, args.host, args.port)
            if args.count == 0 or iteration < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
