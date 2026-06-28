# WeatherFlow Tempest UDP → MQTT Datalogger

Listens for UDP broadcasts from a **WeatherFlow Tempest hub** on the local
network (port 50222) and republishes each message as JSON to an MQTT broker.

## Topic structure

```
weatherdatalogger/tempest-<serial_number>/<message_type>
```

| Message type    | Subtopic         | Source device  |
|-----------------|------------------|----------------|
| Tempest obs     | `observation`    | Tempest (ST-…) |
| Rapid wind      | `rapid_wind`     | Tempest (ST-…) |
| Rain start      | `rain_start`     | Tempest (ST-…) |
| Lightning       | `lightning`      | Tempest (ST-…) |
| Device status   | `device_status`  | Any sensor     |
| Hub status      | `hub_status`     | Hub (HB-…)     |

Example:
```
weatherdatalogger/tempest-ST-00000512/observation
weatherdatalogger/tempest-HB-00013030/hub_status
```

---

## Requirements

- Python 3.10+
- `paho-mqtt` library

---

## Installation on Debian/Proxmox LXC

### 1. Create a dedicated user

```bash
useradd -r -s /usr/sbin/nologin -m -d /opt/tempest-datalogger tempest
```

### 2. Copy files

```bash
mkdir -p /opt/tempest-datalogger
cp tempest_datalogger.py config.ini /opt/tempest-datalogger/
chown -R tempest:tempest /opt/tempest-datalogger
```

### 3. Create a virtual environment and install dependencies

```bash
cd /opt/tempest-datalogger
python3 -m venv venv
venv/bin/pip install --upgrade pip paho-mqtt
```

### 4. Edit the config

```bash
nano /opt/tempest-datalogger/config.ini
```

At minimum set `broker` to the IP/hostname of your MQTT broker.

### 5. Test it manually first

```bash
sudo -u tempest /opt/tempest-datalogger/venv/bin/python3 \
    /opt/tempest-datalogger/tempest_datalogger.py \
    --config /opt/tempest-datalogger/config.ini
```

You should see log lines like:
```
2024-01-15 12:34:56  INFO      Listening for Tempest UDP broadcasts on 0.0.0.0:50222
2024-01-15 12:35:01  INFO      obs_st → weatherdatalogger/tempest-ST-00000512/observation
```

### 6. Install the systemd service

```bash
cp tempest-datalogger.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tempest-datalogger
```

### 7. Check status

```bash
systemctl status tempest-datalogger
journalctl -u tempest-datalogger -f
```

---

## Verifying MQTT output

Subscribe to all datalogger topics with mosquitto_sub:

```bash
mosquitto_sub -h <broker> -t "weatherdatalogger/#" -v
```

### Example `observation` payload

```json
{
  "timestamp": 1588948614,
  "wind_lull_ms": 0.18,
  "wind_avg_ms": 0.22,
  "wind_gust_ms": 0.27,
  "wind_direction_deg": 144,
  "wind_sample_interval_s": 6,
  "station_pressure_mb": 1017.57,
  "air_temperature_c": 22.37,
  "relative_humidity_pct": 50.26,
  "illuminance_lux": 328,
  "uv_index": 0.03,
  "solar_radiation_wm2": 3,
  "rain_accumulation_mm": 0.0,
  "precipitation_type": 0,
  "lightning_avg_dist_km": 0,
  "lightning_strike_count": 0,
  "battery_volts": 2.41,
  "reporting_interval_min": 1,
  "serial_number": "ST-00000512",
  "hub_sn": "HB-00013030",
  "firmware_revision": 129
}
```

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| No UDP packets received | Hub and LXC must be on the **same L2 network** (no routing across VLANs). Check that the Proxmox bridge/VLAN config allows broadcast traffic. |
| MQTT connect failed | Verify broker address/port in config.ini; check firewall rules. |
| Permission denied on port 50222 | Run as root or grant `CAP_NET_BIND_SERVICE`; port 50222 is >1024 so this shouldn't be needed. |
| No data after hub reboot | Hub re-announces within 60 s; wait and check logs. |
