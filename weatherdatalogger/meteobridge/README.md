# Meteobridge → Davis Rain Corrector

Polls a Meteobridge Pro's local REST template API for the Davis Vantage Vue's rain readings — proven consistent with the physical console — and republishes them as corrections to the `davis-vantage-receiver` ESPHome device's own MQTT control topics.

This is **not** a full station integration: it doesn't create its own MQTT observation topic or database rows. It exists purely to correct two known weak points of the CC1101 RF receiver's own rain data:

- **Rain rate needs two tips after every reboot** before it can compute a value (it can't derive a rate from a single data point), so it briefly reads `0` after every reflash/reboot even if it's actively raining.
- **The daily total can drift** from the console's own reading over time.

See [`davis/AGENT.md`](../../AGENT.md#rain-accumulation--rate) ("Rain accumulation & rate") for the full technical background.

## What it publishes

| Topic | Payload | Meaning |
|---|---|---|
| `weatherdatalogger/davis-vantage-receiver/set_daily_rain` | Plain mm, e.g. `5.4` | Today's accumulated rain |
| `weatherdatalogger/davis-vantage-receiver/set_rain_rate` | Plain mm/h, e.g. `2.3` | Current rain rate |

Both are handled by the `mqtt: on_message:` block in [`davis/davis-vantage-receiver.yaml`](../../davis-vantage-receiver.yaml). Neither is retained — these are one-shot corrections re-sent every poll interval, not state to replay to a freshly (re)connecting subscriber.

## Units

The request template asks for plain numeric output and assumes your Meteobridge is configured for **metric units** (mm, mm/h), consistent with the rest of this project. If yours is configured for imperial units, either switch it to metric or adjust `MM_TEMPLATE` in `meteobridge_datalogger.py`.

## Installation

### 1. Install service files

The deploy script copies everything automatically:

```bash
sudo bash /opt/weatherdatalogger/scripts/deploy.sh
```

Files are installed to `/opt/weatherdatalogger/meteobridge/`.

### 2. Configure

All services share a single config file. If it doesn't exist yet:

```bash
cp /opt/weatherdatalogger/config.example.ini /opt/weatherdatalogger/config.ini
nano /opt/weatherdatalogger/config.ini
```

**Required before first start** — the service will log an error and idle (not crash-loop) until this is set:

| Key | Section | What to set |
|---|---|---|
| `host` | `[meteobridge]` | IP address or hostname of the Meteobridge (e.g. `192.168.1.252`) |
| `broker` | `[mqtt]` | Hostname or IP of your MQTT broker |

Everything else has sensible defaults and can be left as-is. This service is entirely optional — leave `host` empty if you don't have a Meteobridge.

### 3. Enable and start

```bash
systemctl enable --now meteobridge-datalogger
journalctl -u meteobridge-datalogger -f
```

You should see a `Meteobridge: rain_today=...mm rain_rate=...mm/h` line every poll interval, matching what you see on the Meteobridge/console.

## Configuration Reference

Settings live in the shared `/opt/weatherdatalogger/config.ini`. Meteobridge-specific keys:

```ini
[meteobridge]
host       =               # REQUIRED — Meteobridge IP address or hostname
port       = 80            # HTTP port (default 80)
username   = meteobridge   # HTTP basic auth username — Meteobridge's own factory default; empty = no auth header sent
password   =               # HTTP basic auth password
interval_s = 60            # Poll interval in seconds
timeout_s  = 10            # HTTP request timeout
```

Shared keys used by this service:

```ini
[mqtt]
broker     = localhost     # REQUIRED — MQTT broker hostname or IP
port       = 1883
username   =
password   =
tls        = false
base_topic = weatherdatalogger
qos        = 0

[logging]
level = INFO
file  =
```

## How the request works

Meteobridge's `template.cgi` endpoint substitutes square-bracket macros in a query string before returning the result. This service requests:

```
[rain0total-act],[rain0rate-act]
```

...and parses the comma-separated response as two floats. An earlier version used a JSON-shaped template (`{"rain_today":[...],"rain_rate":[...]}`) which looked cleaner, but real hardware came back with every quote backslash-escaped (`{\"rain_today\":...}`) — some Meteobridge firmware applies PHP/CGI-style `addslashes()` to template output. The quote-free CSV format sidesteps that: there's nothing left for Meteobridge to escape. See the [Meteobridge Add-On Services wiki](https://www.meteobridge.com/wiki/index.php?title=Add-On_Services) for the full macro reference if you want to pull additional fields.
