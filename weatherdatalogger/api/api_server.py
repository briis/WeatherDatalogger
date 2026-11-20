#!/usr/bin/env python3
"""
WeatherDatalogger API — REST + WebSocket access to the combined views.

A background thread polls both views on a fixed interval and keeps the
latest rows in memory (`DataPoller`). Every request — REST or WebSocket —
is served from that in-memory snapshot; nothing hits MariaDB per-request.

Endpoints (see README.md for the full contract and example payloads):
    GET  /api/v1/health         — liveness check, no auth
    GET  /api/v1/current        — latest snapshot (pull)
    WS   /api/v1/ws/current     — latest snapshot on connect, then again
                                   every time the poller sees it change (push)
    GET  /api/v1/forecast       — latest forecast (current/hourly/daily) for
                                   the configured provider + location
    GET  /api/v1/history        — 10-minute history_charting rows
    GET  /api/v1/daily          — per-local-day summaries from history_charting
    GET  /docs                  — interactive OpenAPI/Swagger docs

Usage:
    python3 api_server.py [--config config.ini]
"""

import argparse
import asyncio
import configparser
import logging
import re
import secrets
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, cast

import pymysql
import pymysql.cursors
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

# ---------------------------------------------------------------------------
# Defaults (overridden by config.ini)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "api": {
        "enabled": "false",  # set true to enable this service
        "host": "0.0.0.0",  # noqa: S104 — deliberately all-interfaces, see README
        "port": "8000",
        "api_key": "",
        "poll_interval_s": "5",
        "cors_origins": "",
        "db_host": "localhost",
        "db_port": "3306",
        "db_name": "weatherdatalogger",
        "db_user": "weatherdatalogger_api",
        "db_password": "",
        # Forecast + history endpoints (used by the web frontend, web/)
        "forecast_provider": "openmeteo",
        "forecast_location": "home",
        "query_cache_ttl_s": "60",
        "timezone": "Europe/Copenhagen",
    },
    "logging": {
        "level": "INFO",
        "file": "",
    },
}

_SQL_CURRENT = "SELECT * FROM combined_realtime LIMIT 1"
_SQL_STATS = "SELECT * FROM combined_realtime_stats LIMIT 1"


# ---------------------------------------------------------------------------
# JSON-safe row conversion — MariaDB rows come back with Decimal/datetime
# values that neither Starlette's WebSocket.send_json nor a plain dict
# response handle out of the box.
# ---------------------------------------------------------------------------


def _jsonify_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value


def _jsonify_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: _jsonify_value(v) for k, v in row.items()}


# ---------------------------------------------------------------------------
# Data poller — one background thread, one shared in-memory snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """The latest known state of both combined views, plus a change counter."""

    version: int
    updated_at: str
    combined_realtime: dict[str, Any] | None
    combined_realtime_stats: dict[str, Any] | None

    def to_message(self) -> dict[str, Any]:
        """Return the JSON-serializable payload shared by REST and WebSocket."""
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "combined_realtime": self.combined_realtime,
            "combined_realtime_stats": self.combined_realtime_stats,
        }


class DataPoller:
    """Polls combined_realtime/combined_realtime_stats and caches the result."""

    def __init__(self, cfg: configparser.ConfigParser, log: logging.Logger) -> None:
        self._cfg = cfg
        self._log = log
        self._conn: pymysql.connections.Connection | None = None
        self._lock = threading.Lock()
        self._snapshot = Snapshot(
            version=0,
            updated_at=datetime.now(UTC).isoformat(),
            combined_realtime=None,
            combined_realtime_stats=None,
        )
        self._connect()

    def _connect(self) -> None:
        a = self._cfg["api"]
        self._conn = pymysql.connect(
            host=a["db_host"],
            port=int(a["db_port"]),
            database=a["db_name"],
            user=a["db_user"],
            password=a["db_password"],
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        self._log.info("Connected to MariaDB at %s/%s", a["db_host"], a["db_name"])

    def _fetch_one(self, sql: str) -> dict[str, Any] | None:
        """Run one SELECT, reconnecting once if the connection was lost."""
        for attempt in range(2):
            try:
                with self._conn.cursor() as cur:  # type: ignore[union-attr]
                    cur.execute(sql)
                    return cast("dict[str, Any] | None", cur.fetchone())
            except (pymysql.OperationalError, pymysql.InterfaceError):
                if attempt == 0:
                    self._log.warning("DB connection lost — reconnecting…")
                    self._connect()
                else:
                    raise
        return None  # unreachable — satisfies static analysis

    @property
    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def poll_once(self) -> None:
        """Fetch both views and update the shared snapshot if anything changed."""
        try:
            current = _jsonify_row(self._fetch_one(_SQL_CURRENT))
            stats = _jsonify_row(self._fetch_one(_SQL_STATS))
        except pymysql.Error:
            self._log.exception("Poll failed")
            return

        with self._lock:
            changed = (
                current != self._snapshot.combined_realtime
                or stats != self._snapshot.combined_realtime_stats
            )
            version = self._snapshot.version + 1 if changed else self._snapshot.version
            self._snapshot = Snapshot(
                version=version,
                updated_at=datetime.now(UTC).isoformat(),
                combined_realtime=current,
                combined_realtime_stats=stats,
            )
        if changed:
            self._log.debug("Snapshot changed — version %d", version)

    def run_forever(self, stop_event: threading.Event) -> None:
        interval = float(self._cfg["api"]["poll_interval_s"])
        while not stop_event.is_set():
            self.poll_once()
            stop_event.wait(interval)


# ---------------------------------------------------------------------------
# On-demand queries — forecast / history / daily summaries
#
# Unlike the two combined views these are larger result sets that change at
# most every few minutes, so they're fetched lazily on first request and then
# served from a short TTL cache (`query_cache_ttl_s`) — repeated page loads
# from any number of clients still cost at most one SELECT per cache window.
# A dedicated connection (not the poller's) guarded by its own lock, since
# PyMySQL connections aren't thread-safe and these endpoints run in
# FastAPI's threadpool.
# ---------------------------------------------------------------------------

HISTORY_MAX_HOURS = 24 * 14
DAILY_MAX_DAYS = 400
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_SQL_FORECAST_CURRENT = (
    "SELECT * FROM forecast_current WHERE provider = %s AND location = %s"
)
_SQL_FORECAST_HOURLY = (
    "SELECT * FROM forecast_hourly WHERE provider = %s AND location = %s "
    "AND forecast_time >= UTC_TIMESTAMP() - INTERVAL 1 HOUR "
    "ORDER BY forecast_time"
)
_SQL_FORECAST_DAILY = (
    "SELECT * FROM forecast_daily WHERE provider = %s AND location = %s "
    "ORDER BY forecast_time"
)
# Per local calendar day. rain_accumulation_mm is a cumulative "so far today"
# counter (see database/README.md), so MAX — not SUM — is the day total.
_SQL_DAILY = """
SELECT
    DATE(CONVERT_TZ(window_start, 'UTC', %(tz)s)) AS day,
    MAX(air_temperature_c)        AS air_temp_high_c,
    MIN(air_temperature_c)        AS air_temp_low_c,
    ROUND(AVG(air_temperature_c), 2) AS air_temp_avg_c,
    ROUND(AVG(relative_humidity_pct), 2) AS relative_humidity_avg_pct,
    ROUND(AVG(dew_point_c), 2)   AS dew_point_avg_c,
    MIN(feels_like_c)             AS feels_like_low_c,
    MAX(feels_like_c)             AS feels_like_high_c,
    ROUND(AVG(sea_level_pressure_mb), 2) AS sea_level_pressure_avg_mb,
    MIN(sea_level_pressure_mb)    AS sea_level_pressure_low_mb,
    MAX(sea_level_pressure_mb)    AS sea_level_pressure_high_mb,
    ROUND(AVG(wind_avg_ms), 2)   AS wind_avg_ms,
    MAX(wind_gust_ms)             AS wind_gust_max_ms,
    MAX(rain_accumulation_mm)     AS rain_total_mm,
    MAX(rain_rate_mmh)            AS rain_rate_max_mmh,
    MAX(uv_index)                 AS uv_index_max,
    MAX(solar_radiation_wm2)      AS solar_radiation_max_wm2,
    MAX(caqi_pm2p5)               AS caqi_pm2p5_max,
    MAX(aqi_pm2p5)                AS aqi_pm2p5_max,
    COUNT(*)                      AS samples
FROM history_charting
WHERE window_start >= UTC_TIMESTAMP() - INTERVAL %(days)s DAY
GROUP BY day
HAVING day IS NOT NULL
ORDER BY day
"""


class QueryService:
    """Lazily-fetched, TTL-cached forecast/history/daily queries."""

    def __init__(self, cfg: configparser.ConfigParser, log: logging.Logger) -> None:
        """Store config; the DB connection is opened lazily on first query."""
        self._cfg = cfg
        self._log = log
        self._conn: pymysql.connections.Connection | None = None
        self._lock = threading.Lock()
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._ttl = float(cfg["api"]["query_cache_ttl_s"])
        self._history_columns: frozenset[str] | None = None

    def _connect(self) -> None:
        a = self._cfg["api"]
        self._conn = pymysql.connect(
            host=a["db_host"],
            port=int(a["db_port"]),
            database=a["db_name"],
            user=a["db_user"],
            password=a["db_password"],
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _fetch_all(
        self, sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run one SELECT (caller holds the lock), reconnecting once if needed."""
        for attempt in range(2):
            try:
                if self._conn is None:
                    self._connect()
                with self._conn.cursor() as cur:  # type: ignore[union-attr]
                    cur.execute(sql, params)
                    return [
                        cast("dict[str, Any]", _jsonify_row(r)) for r in cur.fetchall()
                    ]
            except (pymysql.OperationalError, pymysql.InterfaceError):
                if attempt == 0:
                    self._log.warning("Query connection lost — reconnecting…")
                    self._conn = None
                else:
                    raise
        return []  # unreachable — satisfies static analysis

    def _cached(self, key: tuple[Any, ...], producer: Any) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < self._ttl:
                return hit[1]
            value = producer()
            self._cache[key] = (now, value)
            # Keep the cache bounded — drop anything expired
            for k in [k for k, (t, _) in self._cache.items() if now - t >= self._ttl]:
                if k != key:
                    del self._cache[k]
            return value

    def history_columns(self) -> frozenset[str]:
        """Return the set of selectable history_charting columns."""
        with self._lock:
            if self._history_columns is None:
                for attempt in range(2):
                    try:
                        if self._conn is None:
                            self._connect()
                        with self._conn.cursor() as cur:  # type: ignore[union-attr]
                            cur.execute("SELECT * FROM history_charting LIMIT 0")
                            self._history_columns = frozenset(
                                d[0] for d in cur.description or ()
                            ) - {"id"}
                        break
                    except (pymysql.OperationalError, pymysql.InterfaceError):
                        self._conn = None
                        if attempt == 1:
                            raise
            return self._history_columns or frozenset()

    def forecast(self) -> dict[str, Any]:
        """Return the latest forecast fetch for the configured provider/location."""
        a = self._cfg["api"]
        provider, location = a["forecast_provider"], a["forecast_location"]

        def produce() -> dict[str, Any]:
            current = self._fetch_all(_SQL_FORECAST_CURRENT, (provider, location))
            return {
                "provider": provider,
                "location": location,
                "current": current[0] if current else None,
                "hourly": self._fetch_all(_SQL_FORECAST_HOURLY, (provider, location)),
                "daily": self._fetch_all(_SQL_FORECAST_DAILY, (provider, location)),
            }

        return cast("dict[str, Any]", self._cached(("forecast",), produce))

    def history(self, hours: int, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        """Return history_charting rows for the trailing `hours` (fields vetted)."""
        cols = ", ".join(("window_start", *fields))
        sql = (
            f"SELECT {cols} FROM history_charting "  # noqa: S608 — fields whitelisted
            "WHERE window_start >= UTC_TIMESTAMP() - INTERVAL %s HOUR "
            "ORDER BY window_start"
        )
        return cast(
            "list[dict[str, Any]]",
            self._cached(
                ("history", hours, fields), lambda: self._fetch_all(sql, (hours,))
            ),
        )

    def daily(self, days: int) -> list[dict[str, Any]]:
        """Return per-local-day summaries for the trailing `days`."""
        tz = self._cfg["api"]["timezone"]
        return cast(
            "list[dict[str, Any]]",
            self._cached(
                ("daily", days),
                lambda: self._fetch_all(_SQL_DAILY, {"tz": tz, "days": days}),
            ),
        )


# ---------------------------------------------------------------------------
# Auth — single shared API key, checked via header (REST) or query param (WS)
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _expected_api_key(app: FastAPI) -> str:
    cfg: configparser.ConfigParser = app.state.cfg
    return cfg["api"]["api_key"]


def require_api_key(
    request: Request,
    api_key: str | None = Depends(_api_key_header),
) -> None:
    """FastAPI dependency: reject the request unless X-API-Key matches config."""
    expected = _expected_api_key(request.app)
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    poller: DataPoller = app.state.poller
    stop_event = threading.Event()
    thread = threading.Thread(
        target=poller.run_forever, args=(stop_event,), daemon=True
    )
    thread.start()
    yield
    stop_event.set()
    thread.join(timeout=5)


app = FastAPI(
    title="WeatherDatalogger API",
    description=(
        "Read-only REST + WebSocket access to WeatherDatalogger's "
        "combined_realtime / combined_realtime_stats views, plus forecast "
        "and history_charting queries. "
        "See weatherdatalogger/api/README.md for the full field reference."
    ),
    version="1",
    lifespan=_lifespan,
)


@app.get("/api/v1/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness check — no auth required."""
    return {"status": "ok"}


@app.get(
    "/api/v1/current",
    tags=["observations"],
    dependencies=[Depends(require_api_key)],
)
async def get_current() -> dict[str, Any]:
    """Return the latest combined_realtime + combined_realtime_stats snapshot."""
    snapshot = app.state.poller.snapshot
    if snapshot.combined_realtime is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No observation data yet — no station reporting the 'wind' "
                "role is registered (see station_roles in the database docs)."
            ),
        )
    return snapshot.to_message()


@app.websocket("/api/v1/ws/current")
async def ws_current(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
) -> None:
    """Push the combined snapshot on connect, then again on every change."""
    # Browsers can't set headers on the WS handshake, but a reverse proxy can
    # (web/ deploys Caddy injecting X-API-Key so the key never reaches the
    # browser) — accept either.
    api_key = api_key or websocket.headers.get("x-api-key")
    expected = _expected_api_key(websocket.app)
    if not api_key or not secrets.compare_digest(api_key, expected):
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()
    poller: DataPoller = websocket.app.state.poller
    check_interval_s = float(websocket.app.state.cfg["api"]["poll_interval_s"])
    last_sent_version = -1
    try:
        while True:
            snapshot = poller.snapshot
            if snapshot.version != last_sent_version:
                await websocket.send_json(snapshot.to_message())
                last_sent_version = snapshot.version
            with suppress(TimeoutError):
                # Doubles as our tick and as disconnect detection — any
                # inbound frame (or none, within the timeout) is fine, we
                # never act on client messages, only push.
                await asyncio.wait_for(
                    websocket.receive_text(), timeout=check_interval_s
                )
    except WebSocketDisconnect:
        return


@app.get(
    "/api/v1/forecast",
    tags=["forecast"],
    dependencies=[Depends(require_api_key)],
)
def get_forecast() -> dict[str, Any]:
    """Latest forecast fetch (current + hourly + daily) for the configured provider."""
    try:
        return app.state.queries.forecast()
    except pymysql.Error as err:
        app.state.log.exception("Forecast query failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from err


@app.get(
    "/api/v1/history",
    tags=["history"],
    dependencies=[Depends(require_api_key)],
)
def get_history(
    hours: Annotated[int, Query(ge=1, le=HISTORY_MAX_HOURS)] = 24,
    fields: Annotated[
        str, Query(description="Comma-separated history_charting column names")
    ] = "air_temperature_c",
) -> dict[str, Any]:
    """Return 10-minute history_charting rows for the trailing `hours`."""
    queries: QueryService = app.state.queries
    requested = tuple(dict.fromkeys(f.strip() for f in fields.split(",") if f.strip()))
    try:
        allowed = queries.history_columns()
        bad = [f for f in requested if not _FIELD_RE.match(f) or f not in allowed]
        if bad or not requested:
            raise HTTPException(
                status_code=422, detail=f"Unknown field(s): {', '.join(bad) or '-'}"
            )
        rows = queries.history(hours, requested)
    except pymysql.Error as err:
        app.state.log.exception("History query failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from err
    return {"hours": hours, "fields": list(requested), "rows": rows}


@app.get(
    "/api/v1/daily",
    tags=["history"],
    dependencies=[Depends(require_api_key)],
)
def get_daily(
    days: Annotated[int, Query(ge=1, le=DAILY_MAX_DAYS)] = 30,
) -> dict[str, Any]:
    """Return one summary row per local calendar day for the trailing `days`."""
    try:
        rows = app.state.queries.daily(days)
    except pymysql.Error as err:
        app.state.log.exception("Daily query failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from err
    return {"days": days, "timezone": app.state.cfg["api"]["timezone"], "rows": rows}


def _configure_cors(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    origins = [o.strip() for o in cfg["api"]["cors_origins"].split(",") if o.strip()]
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET"],
        allow_headers=["X-API-Key"],
    )
    log.info("CORS enabled for: %s", ", ".join(origins))


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
    return logging.getLogger("weatherdatalogger.api")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(cfg: configparser.ConfigParser, log: logging.Logger) -> None:
    a = cfg["api"]
    if not a.getboolean("enabled"):
        log.info("[api] enabled = false — exiting")
        return
    if not a["api_key"].strip():
        log.error(
            "No [api] api_key configured — refusing to start with an "
            "unauthenticated API. Set [api] api_key in config.ini and restart."
        )
        return
    if not a["db_password"]:
        log.error(
            "[api] db_password is not configured. Set it in config.ini "
            "(see scripts/create_api_readonly_user.sh to create that DB user) "
            "and restart."
        )
        return

    app.state.cfg = cfg
    app.state.log = log
    app.state.poller = DataPoller(cfg, log)
    app.state.queries = QueryService(cfg, log)
    _configure_cors(cfg, log)

    log.info("Starting API server on %s:%s", a["host"], a["port"])
    uvicorn.run(app, host=a["host"], port=int(a["port"]), log_config=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="WeatherDatalogger API")
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
