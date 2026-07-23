# WeatherDatalogger API

A read-only REST + WebSocket API in front of the `combined_realtime` and
`combined_realtime_stats` database views — the same "current conditions"
data documented in [`database/README.md`](../database/README.md). Built for
dashboards, mobile/web apps, or any consumer that shouldn't need direct
database credentials or MQTT access.

> **Installation:** Follow the [server installation guide](../../README.md#installation-debian--proxmox-lxc) first, then return here to configure the API.

---

## What it does

- Polls `combined_realtime` and `combined_realtime_stats` on a fixed interval (`poll_interval_s`, default 5s) and keeps the latest rows in an in-memory cache — **every REST/WebSocket request is served from that cache**, not a fresh query, so response latency doesn't depend on database load
- `GET /api/v1/current` — pull the latest snapshot on demand
- `WS /api/v1/ws/current` — push model: sends the snapshot immediately on connect, then again every time the poller sees either view change — no polling from the client needed
- Interactive API docs (OpenAPI/Swagger UI) at `/docs`, and the raw schema at `/openapi.json`
- Single shared API-key auth (`X-API-Key` header for REST, `?api_key=` query parameter for WebSocket)
- Uses its own SELECT-only database user (`weatherdatalogger_api`) — never the `weatherlogger` writer user

This is v1 scope: just the two combined-view "current conditions" endpoints. Historical (`history_charting`) and forecast (`forecast_*`) endpoints can be added later the same way if needed.

---

## Setup

After completing the [server installation](../../README.md#installation-debian--proxmox-lxc):

1. Create the read-only database user:

   ```bash
   sudo bash /opt/weatherdatalogger/scripts/create_api_readonly_user.sh
   ```

2. Generate an API key and edit the shared config file:

   ```bash
   tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; echo
   nano /opt/weatherdatalogger/config.ini
   ```

   Minimum required settings:

   ```ini
   [api]
   enabled     = true
   api_key     = <the key you just generated>
   db_password = <the password you set for weatherdatalogger_api>
   ```

3. Enable and start the service:

   ```bash
   systemctl enable --now weatherdatalogger-api
   ```

4. Verify:

   ```bash
   journalctl -u weatherdatalogger-api -f
   curl http://localhost:8000/api/v1/health
   ```

---

## Configuration

All settings live in the shared `/opt/weatherdatalogger/config.ini`, under `[api]`. See [`config.example.ini`](config.example.ini) for the full commented template.

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Service idles (exits cleanly) until set `true` |
| `host` | `0.0.0.0` | Interface to bind — see [Exposing this beyond your LAN](#exposing-this-beyond-your-lan) |
| `port` | `8000` | TCP port |
| `api_key` | _(empty)_ | **Required.** Shared secret clients must present. The service refuses to start without one |
| `poll_interval_s` | `5` | How often the cache refreshes from the database — the worst-case latency for both REST reads and WebSocket pushes |
| `cors_origins` | _(empty)_ | Comma-separated allowed browser origins, e.g. `https://dashboard.example.com`. Empty = no CORS headers added (fine for server-to-server or reverse-proxied same-origin use; a browser app calling this API cross-origin needs its origin listed here) |
| `db_host` / `db_port` / `db_name` | `localhost` / `3306` / `weatherdatalogger` | Database connection |
| `db_user` | `weatherdatalogger_api` | **Use a SELECT-only user** — see Setup step 1 |
| `db_password` | _(empty)_ | **Required** |

---

## Authentication

Every endpoint except `/api/v1/health` and the docs (`/docs`, `/redoc`, `/openapi.json`) requires the API key configured above.

**REST** — send it as a header:

```bash
curl -H "X-API-Key: <your key>" http://localhost:8000/api/v1/current
```

**WebSocket** — browsers can't set custom headers on the handshake, so send it as a query parameter instead:

```
ws://localhost:8000/api/v1/ws/current?api_key=<your key>
```

A missing or wrong key gets a `401` on REST, or the WebSocket handshake is rejected outright (HTTP `403` before any upgrade — the connection is never accepted).

---

## REST endpoints

### `GET /api/v1/health`

No auth required. Liveness check for load balancers / monitoring.

```json
{"status": "ok"}
```

### `GET /api/v1/current`

Returns the latest snapshot of both views. `503` if no station reporting the `wind` role is registered yet (that role anchors `combined_realtime` — see [`database/README.md`](../database/README.md#combined_realtime-view)).

```json
{
  "version": 42,
  "updated_at": "2026-07-23T17:45:29.409894+00:00",
  "combined_realtime": {
    "recorded_at": "2026-07-23T17:45:07",
    "air_temperature_c": 21.5,
    "relative_humidity_pct": 55.0,
    "wind_avg_ms": 3.2,
    "wind_direction_deg": 180,
    "...": "one key per combined_realtime column — see database/README.md"
  },
  "combined_realtime_stats": {
    "wind_gust_high_today": 8.1,
    "air_temp_high_today": 23.4,
    "air_temp_low_today": 15.2,
    "...": "one key per combined_realtime_stats column"
  }
}
```

- `version` — increments only when either view's content actually changes since the last poll; useful for cheaply detecting "nothing new" without diffing the payload yourself
- `updated_at` — UTC timestamp of the poll that produced this snapshot (not the same as `combined_realtime.recorded_at`, which is when the underlying station reading was taken)
- Field names, types, units, and which physical station sources each field are documented in [`database/README.md`](../database/README.md#combined_realtime-view) — this API is a thin pass-through and doesn't duplicate that reference
- `NULL` fields mean that role's station isn't registered yet (e.g. no AirLink configured → all `pm_*`/`aqi_*`/`caqi_*` fields are `null`)

---

## WebSocket

### `WS /api/v1/ws/current`

On connect, sends one message with the current snapshot immediately, then sends a new message every time `poll_once()` detects either view changed — same payload shape as `GET /api/v1/current`. The connection never expects anything from the client; any inbound frame is ignored (harmless to send pings).

**Python example — quick test script:**

Install the client library (separate from anything this project's own services need — this only runs on your workstation, not the server):

```bash
pip install websockets
```

Save as `test_ws.py` and run it — it connects, prints the initial snapshot, then prints each subsequent push as it arrives (trigger one by letting a station report a new reading, or by hand: `UPDATE realtime SET air_temperature_c = 20.0 WHERE station_id = '<id>';`):

```python
#!/usr/bin/env python3
"""Quick manual test for WS /api/v1/ws/current — connects, prints every push."""

import argparse
import asyncio
import json

import websockets


async def main(host: str, port: int, api_key: str, use_tls: bool) -> None:
    scheme = "wss" if use_tls else "ws"
    uri = f"{scheme}://{host}:{port}/api/v1/ws/current?api_key={api_key}"
    print(f"Connecting to {uri} ...")

    async with websockets.connect(uri) as ws:
        print("Connected — waiting for pushes (Ctrl+C to stop)\n")
        async for message in ws:
            data = json.loads(message)
            current = data["combined_realtime"] or {}
            print(
                f"[version {data['version']}] updated_at={data['updated_at']} "
                f"air_temperature_c={current.get('air_temperature_c')} "
                f"wind_avg_ms={current.get('wind_avg_ms')}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--tls", action="store_true", help="use wss:// instead of ws://")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.port, args.api_key, args.tls))
    except KeyboardInterrupt:
        print("\nStopped.")
```

```bash
python3 test_ws.py --host localhost --port 8000 --api-key <your key>
```

A wrong `--api-key` raises `websockets.exceptions.InvalidStatus` with an HTTP `403` — that's the expected rejection, not a bug in the script (see [Authentication](#authentication) above).

**JavaScript (browser) example:**

```javascript
const ws = new WebSocket("wss://your-host/api/v1/ws/current?api_key=your-key-here");
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.version, data.combined_realtime.air_temperature_c);
};
```

**websocat (CLI, for quick testing):**

```bash
websocat "ws://localhost:8000/api/v1/ws/current?api_key=your-key-here"
```

If you'd rather poll than hold a connection open, `GET /api/v1/current` on your own interval works identically — both are served from the same in-memory cache, so neither is "more expensive" than the other.

---

## Interactive docs

FastAPI generates a full interactive OpenAPI page automatically:

- `http://<host>:<port>/docs` — Swagger UI, lets you fill in the `X-API-Key` header (click "Authorize") and try requests from the browser
- `http://<host>:<port>/redoc` — ReDoc, read-only reference view
- `http://<host>:<port>/openapi.json` — raw OpenAPI 3 schema, for generating a typed client

---

## Exposing this beyond your LAN

`host = 0.0.0.0` binds all interfaces so the service is reachable on your LAN out of the box, same as the rest of this project. If you want to reach it from outside your network (a phone app, a hosted dashboard):

- Put it behind a reverse proxy (nginx, Caddy, Traefik) that terminates TLS — this service speaks plain HTTP only, no built-in TLS
- The reverse proxy must support WebSocket upgrades (`Connection: Upgrade` / `Upgrade: websocket` headers) for `/api/v1/ws/current` to work — both nginx and Caddy do this, but nginx needs it configured explicitly (`proxy_set_header Upgrade $http_upgrade;` etc.)
- The API key is the only access control here — treat it like a password (don't commit it, rotate it if it leaks by editing `[api] api_key` in `config.ini` and restarting the service)

---

## Troubleshooting

- **Service exits immediately after `enabled = true`** — check `journalctl -u weatherdatalogger-api` for which required setting is missing (`api_key` or `db_password`); the service refuses to start rather than run unauthenticated or without a working DB connection
- **`503` from `/api/v1/current`** — no station is registered for the `wind` role yet (the mandatory anchor in `combined_realtime`); check `station_roles` and confirm at least one station has published an observation
- **WebSocket handshake fails with `403`** — wrong or missing `api_key` query parameter
- **Stale data** — the cache only refreshes every `poll_interval_s`; lower it if you need fresher data (at the cost of one more `SELECT` pair per interval)
