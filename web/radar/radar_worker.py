#!/usr/bin/env python3
"""
DMI radar → transparent Web Mercator PNG frames for the web frontend.

Runs as a oneshot from a systemd timer (every 5 min) in the weather-web LXC:

  1. List DMI's composite radar files for the last `keep_minutes`
     (opendataapi.dmi.dk, no API key, doppler scan by default — ~5 min
     fresher than fullRange, and it covers Zealand fully)
  2. Download + render every frame not rendered yet:
       HDF5 (ODIM, stereographic, 500 m, uint8 dBZ) → colour LUT →
       reprojected onto a Web Mercator grid over `bounds`
  3. Delete frames older than `keep_minutes`, write frames.json

Caddy serves the output directory as /radar/*. The frontend overlays the
PNGs with Leaflet's imageOverlay using the bounds from frames.json, which
works because the PNG grid is linear in Web Mercator.

Reading/decoding and the projection are ported from the pydmi radar spike
(briis/pydmi, branch spike/radar): pyfive (pure-Python HDF5, no compiled
libhdf5), DMI's scaling in the ROOT `what`, and Snyder's oblique
stereographic in numpy (identical to PROJ on DMI's grid, so no pyproj).

Usage:
    python3 radar_worker.py [--config /etc/weather-radar.ini] [--file X.h5 ...]
"""

# ruff: noqa: SIM118 — pyfive groups need .keys() for membership tests
from __future__ import annotations

import argparse
import configparser
import contextlib
import hashlib
import io
import json
import logging
import math
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyfive
from PIL import Image

VERSION = "0.2.0"
BASE = "https://opendataapi.dmi.dk/v1/radardata"
UA = f"weatherdatalogger-web-radar/{VERSION} (+https://github.com/briis/WeatherDatalogger)"

DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "radar": {
        "enabled": "true",
        "scan_type": "doppler",  # doppler | fullRange
        "keep_minutes": "120",
        "output_dir": "/var/lib/weather-web/radar",
        # Last frame + fixed-echo statistics between runs (not served)
        "state_dir": "/var/lib/weather-web/radar-state",
        # Extrapolated frames for the next hour (0 = off)
        "forecast": "true",
        # Area rendered (W, S, E, N). Default: DMI's radar coverage over DK
        "bounds": "6.6,53.9,16.0,58.2",
        "width_px": "1200",
        # Echo below this is not drawn (dBZ) — DMI's own map starts ~5-7 dBZ
        "min_dbz": "7",
        "timeout_s": "30",
    },
    "logging": {"level": "INFO"},
}

log = logging.getLogger("weather-web.radar")


# ── DMI API ────────────────────────────────────────────────────────────────


def http_get(url: str, timeout: float) -> bytes:
    """GET with a descriptive User-Agent (DMI asks for fair use)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310 — fixed https host
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def list_frames(scan: str, since: datetime, timeout: float) -> list[dict[str, Any]]:
    """Composite items newer than `since`, oldest first."""
    q = urllib.parse.urlencode(
        {
            "scanType": scan,
            "datetime": f"{since.strftime('%Y-%m-%dT%H:%M:%SZ')}/..",
            "limit": 100,
        }
    )
    data = json.loads(http_get(f"{BASE}/collections/composite/items?{q}", timeout))
    items = [
        {
            "id": f["id"],
            "href": f["asset"]["data"]["href"],
            "time": datetime.fromisoformat(
                f["properties"]["datetime"].replace("Z", "+00:00")
            ),
        }
        for f in data.get("features", [])
    ]
    return sorted(items, key=lambda x: x["time"])


# ── ODIM HDF5 ──────────────────────────────────────────────────────────────


def _attrs(obj: Any) -> dict[str, Any]:
    """Attributes as plain values (pyfive returns scalars as 1-element arrays)."""
    out: dict[str, Any] = {}
    for k, raw in obj.attrs.items():
        v = raw.tolist() if hasattr(raw, "tolist") else raw
        if isinstance(v, list) and len(v) == 1:
            v = v[0]
        if isinstance(v, bytes):
            v = v.decode(errors="replace")
        out[k] = v
    return out


def read_odim(raw_h5: bytes) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    """Return (uint8 grid, merged `what`, root `where`) from a composite file."""
    with tempfile.NamedTemporaryFile(suffix=".h5") as tmp:
        tmp.write(raw_h5)
        tmp.flush()
        f = pyfive.File(tmp.name)
        where = _attrs(f["where"]) if "where" in f.keys() else {}
        # DMI puts gain/offset/nodata/undetect in the ROOT what and quantity on
        # the data group — merge all levels, most specific last
        root_what = _attrs(f["what"]) if "what" in f.keys() else {}
        for ds in sorted(k for k in f.keys() if k.startswith("dataset")):
            ds_what = _attrs(f[ds]["what"]) if "what" in f[ds].keys() else {}
            for dk in sorted(k for k in f[ds].keys() if k.startswith("data")):
                node = f[ds][dk]
                if "data" not in node.keys():
                    continue
                node_what = _attrs(node["what"]) if "what" in node.keys() else {}
                what = {**root_what, **ds_what, **_attrs(node), **node_what}
                return np.asarray(node["data"][()]), what, where
    msg = "No dataset*/data*/data in radar file"
    raise ValueError(msg)


def scan_time(what: dict[str, Any]) -> datetime | None:
    """Nominal scan time from ODIM what/date+time."""
    try:
        return datetime.strptime(
            f"{what['date']}{str(what['time'])[:4]}", "%Y%m%d%H%M"
        ).replace(tzinfo=UTC)
    except (KeyError, ValueError):
        return None


# ── Projection ─────────────────────────────────────────────────────────────

_A = 6378137.0
_F = 1 / 298.257223563
_E = math.sqrt(_F * (2 - _F))


def _projdef(projdef: str) -> dict[str, str]:
    return dict(
        p[1:].split("=", 1) for p in projdef.split() if p.startswith("+") and "=" in p
    )


def stere_xy(
    projdef: str, lat: np.ndarray, lon: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Oblique stereographic on WGS84 (Snyder 1987 eq. 21-27), vectorised."""
    p = _projdef(projdef)
    if p.get("proj") != "stere" or p.get("ellps", "WGS84") != "WGS84":
        msg = f"unsupported projection: {projdef}"
        raise ValueError(msg)
    k0 = float(p.get("k", p.get("k_0", 1.0)))
    phi0, lam0 = math.radians(float(p["lat_0"])), math.radians(float(p["lon_0"]))
    phi, lam = np.radians(lat), np.radians(lon)

    def chi(ph: Any) -> Any:  # conformal latitude
        es = _E * np.sin(ph)
        return (
            2
            * np.arctan(np.tan(np.pi / 4 + ph / 2) * ((1 - es) / (1 + es)) ** (_E / 2))
            - np.pi / 2
        )

    m0 = math.cos(phi0) / math.sqrt(1 - (_E * math.sin(phi0)) ** 2)
    c0 = float(chi(phi0))
    c = chi(phi)
    dl = lam - lam0
    big_a = (
        2
        * _A
        * k0
        * m0
        / (
            math.cos(c0)
            * (1 + math.sin(c0) * np.sin(c) + math.cos(c0) * np.cos(c) * np.cos(dl))
        )
    )
    x = big_a * np.cos(c) * np.sin(dl)
    y = big_a * (math.cos(c0) * np.sin(c) - math.sin(c0) * np.cos(c) * np.cos(dl))
    return x, y


def merc_y(lat: float) -> float:
    """Web Mercator y (unit sphere) for a latitude in degrees."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


class Grid:
    """
    Output grid, linear in Web Mercator over (W, S, E, N).

    Holds the lookup from every output pixel into the radar grid; cached per
    (radar geometry, bounds, width).
    """

    def __init__(
        self,
        where: dict[str, Any],
        src_shape: tuple[int, int],
        bounds: list[float],
        width: int,
    ) -> None:
        """Build the lon/lat of every output pixel and its source index."""
        w, s, e, n = bounds
        y_top, y_bot = merc_y(n), merc_y(s)
        height = round(width * (y_top - y_bot) / math.radians(e - w))
        self.width, self.height, self.bounds = width, height, bounds

        lon = np.linspace(w, e, width, dtype=np.float64)
        my = np.linspace(y_top, y_bot, height, dtype=np.float64)
        lat = np.degrees(2 * np.arctan(np.exp(my)) - np.pi / 2)
        lon2, lat2 = np.meshgrid(lon, lat)

        x, y = stere_xy(where["projdef"], lat2, lon2)
        ul_x, ul_y = stere_xy(
            where["projdef"],
            np.array(float(where["UL_lat"])),
            np.array(float(where["UL_lon"])),
        )
        col = np.floor((x - float(ul_x)) / float(where["xscale"])).astype(np.int64)
        row = np.floor((float(ul_y) - y) / float(where["yscale"])).astype(np.int64)
        rows, cols = src_shape
        self.inside = (col >= 0) & (col < cols) & (row >= 0) & (row < rows)
        self.flat = np.where(self.inside, row * cols + col, 0)

    @staticmethod
    def key(
        where: dict[str, Any], shape: tuple[int, int], bounds: list[float], width: int
    ) -> str:
        """Cache key for a radar geometry + output configuration."""
        parts = [
            str(where.get(k))
            for k in ("projdef", "UL_lat", "UL_lon", "xscale", "yscale")
        ]
        return hashlib.sha1(  # noqa: S324 — cache key, not security
            "|".join([*parts, str(shape), str(bounds), str(width)]).encode()
        ).hexdigest()


# ── Colour ─────────────────────────────────────────────────────────────────

# dBZ → RGBA, blues (light) → greens → yellow → orange → red → magenta (hail)
_STOPS = [
    (5, (120, 200, 255, 0)),
    (10, (110, 190, 255, 140)),
    (18, (40, 130, 245, 175)),
    (25, (30, 190, 90, 195)),
    (32, (240, 225, 40, 210)),
    (38, (250, 150, 20, 225)),
    (45, (235, 50, 30, 235)),
    (52, (200, 0, 120, 245)),
    (60, (190, 60, 255, 250)),
]


def colour_lut(what: dict[str, Any], min_dbz: float) -> np.ndarray:
    """256-entry RGBA lookup for the file's raw uint8 values."""
    gain, offset = float(what.get("gain", 1.0)), float(what.get("offset", 0.0))
    dbz = np.arange(256, dtype=np.float64) * gain + offset
    lut = np.zeros((256, 4), dtype=np.float64)
    xs = [s[0] for s in _STOPS]
    for ch in range(4):
        lut[:, ch] = np.interp(dbz, xs, [s[1][ch] for s in _STOPS])
    lut[dbz < min_dbz] = 0
    for k in ("nodata", "undetect"):
        if k in what:
            lut[int(what[k])] = 0
    return lut.astype(np.uint8)


def render(raw: np.ndarray, what: dict[str, Any], grid: Grid, min_dbz: float) -> bytes:
    """uint8 radar grid → PNG bytes on the output grid."""
    lut = colour_lut(what, min_dbz)
    rgba = lut[raw.reshape(-1)[grid.flat]]
    rgba[~grid.inside] = 0
    img = Image.fromarray(rgba.reshape(grid.height, grid.width, 4), "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Nowcast: motion, ETA, nearest rain, forecast frames ───────────────────
#
# Ported from the pydmi radar spike (briis/pydmi, spike/radar), which was
# checked against the station's rain gauge: plain FFT cross-correlation of
# the log rain fields (big areas dominate; phase correlation locked onto
# echoes that never move) plus a "fixed echo" mask — pixels that echo in
# >= 80 % of recent frames (masts, turbines, ships at anchor) are ignored.

RAIN_MMH = 0.2
MAX_SPEED_KMH = 150
WINDOW_KM = 150
CLUTTER_FRAMES = 36  # ~6 h of history (EMA horizon)
CLUTTER_FREQ = 0.8
CLUTTER_MIN_FRAMES = 18  # only after ~3 h of history
FORECAST_STEPS_MIN = (10, 20, 30, 40, 50, 60)
MIN_TRACK_QUALITY = 0.3
COMPASS_DA = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]


def rate_from_raw(raw: np.ndarray, what: dict[str, Any]) -> np.ndarray:
    """mm/h grid (float32); nodata → NaN, undetect / weak echo → 0."""
    gain, offset = float(what.get("gain", 1.0)), float(what.get("offset", 0.0))
    dbz = raw.astype(np.float32) * gain + offset
    with np.errstate(invalid="ignore", over="ignore"):
        rate = (np.power(10.0, dbz / 10.0) / 200.0) ** (1.0 / 1.6)
    rate[dbz < 7] = 0.0  # noqa: PLR2004 — below DMI's own map threshold
    if "undetect" in what:
        rate[raw == int(what["undetect"])] = 0.0
    if "nodata" in what:
        rate[raw == int(what["nodata"])] = np.nan
    return rate


def to_pixels(
    where: dict[str, Any], lat: float, lon: float
) -> tuple[float, float, float]:
    """(col, row, pixel size m) of a point in the radar grid."""
    x, y = stere_xy(where["projdef"], np.array(lat), np.array(lon))
    ux, uy = stere_xy(
        where["projdef"],
        np.array(float(where["UL_lat"])),
        np.array(float(where["UL_lon"])),
    )
    px = float(where["xscale"])
    return (
        (float(x) - float(ux)) / px,
        (float(uy) - float(y)) / float(where["yscale"]),
        px,
    )


def grid_north_deg(where: dict[str, Any], lat: float, lon: float) -> float:
    """Clockwise angle of true north as seen in the grid at the point."""
    x0, y0 = stere_xy(where["projdef"], np.array(lat), np.array(lon))
    x1, y1 = stere_xy(where["projdef"], np.array(lat + 0.01), np.array(lon))
    return math.degrees(math.atan2(float(x1 - x0), float(y1 - y0)))


def _neighbours(mask: np.ndarray) -> np.ndarray:
    p = np.pad(mask.astype(np.uint8), 1)
    h, w = mask.shape
    return sum(p[dy : dy + h, dx : dx + w] for dy in range(3) for dx in range(3))


def local_rate(rate: np.ndarray, col: float, row: float, half: int = 1) -> float:
    """Mean over (2·half+1)² pixels (3x3 = 1.5 km), NaN-safe."""
    c, r = round(col), round(row)
    h, w = rate.shape
    box = rate[
        max(0, r - half) : min(h, r + half + 1), max(0, c - half) : min(w, c + half + 1)
    ]
    if box.size == 0 or np.all(np.isnan(box)):
        return float("nan")
    return float(np.nanmean(box))


class EchoState:
    """Last frame + fixed-echo frequency, kept between runs in state_dir."""

    def __init__(self, path: Path) -> None:
        """Load state if present (and compatible), else start empty."""
        self.path = path
        self.raw: np.ndarray | None = None
        self.what: dict[str, Any] = {}
        self.time: str | None = None
        self.freq: np.ndarray | None = None
        self.n = 0
        try:
            z = np.load(path, allow_pickle=False)
            self.raw, self.freq, self.n = (
                z["raw"],
                z["freq"].astype(np.float32),
                int(z["n"]),
            )
            self.time = str(z["time"])
            self.what = json.loads(str(z["what"]))
        except (OSError, KeyError, ValueError):
            pass

    def add(
        self, raw: np.ndarray, what: dict[str, Any], stamp: str, min_dbz: float
    ) -> None:
        """Fold one frame into the echo frequency (EMA over ~CLUTTER_FRAMES)."""
        gain, offset = float(what.get("gain", 1.0)), float(what.get("offset", 0.0))
        echo = ((raw.astype(np.float32) * gain + offset) >= min_dbz).astype(np.float32)
        if "nodata" in what:
            echo[raw == int(what["nodata"])] = 0.0
        if self.freq is None or self.freq.shape != raw.shape:
            self.freq, self.n = echo, 1
        else:
            a = 1.0 / min(self.n + 1, CLUTTER_FRAMES)
            self.freq = (1 - a) * self.freq + a * echo
            self.n += 1
        self.raw, self.what, self.time = raw, what, stamp

    def clutter(self) -> np.ndarray | None:
        """Pixels treated as fixed echoes (None until enough history)."""
        if self.freq is None or self.n < CLUTTER_MIN_FRAMES:
            return None
        return self.freq >= CLUTTER_FREQ

    def save(self) -> None:
        """Persist atomically."""
        if self.raw is None or self.freq is None:
            return
        tmp = self.path.with_suffix(".tmp.npz")
        np.savez_compressed(
            tmp,
            raw=self.raw,
            freq=self.freq.astype(np.float16),
            n=self.n,
            time=self.time or "",
            what=json.dumps(
                {k: v for k, v in self.what.items() if isinstance(v, (int, float, str))}
            ),
        )
        tmp.replace(self.path)


def track(  # noqa: PLR0913, PLR0917
    prev: np.ndarray,
    now: np.ndarray,
    minutes: float,
    col: float,
    row: float,
    px: float,
    clutter: np.ndarray | None,
) -> dict[str, float] | None:
    """Shift (pixels per minute) of the rain field between two rate grids."""
    half = int(WINDOW_KM * 1000 / px)
    r, c = round(row), round(col)
    h, w = now.shape
    r0, r1, c0, c1 = (
        max(0, r - half),
        min(h, r + half),
        max(0, c - half),
        min(w, c + half),
    )

    def field(rate: np.ndarray) -> np.ndarray:
        f = np.nan_to_num(rate[r0:r1, c0:c1], nan=0.0)
        if clutter is not None:
            f = np.where(clutter[r0:r1, c0:c1], 0.0, f)
        f = np.where(f >= RAIN_MMH, f, 0.0)
        f = np.where(_neighbours(f > 0) >= 3, f, 0.0)  # noqa: PLR2004 — despeckle
        return np.log1p(f)

    a, b = field(now), field(prev)
    if min((a > 0).sum(), (b > 0).sum()) < 50:  # noqa: PLR2004
        return None
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    a, b = (a - a.mean()) * win, (b - b.mean()) * win
    shape = (a.shape[0] * 2, a.shape[1] * 2)
    cc = np.fft.irfft2(np.fft.rfft2(a, shape) * np.conj(np.fft.rfft2(b, shape)), shape)
    cc /= math.sqrt(float((a * a).sum() * (b * b).sum())) or 1.0
    max_px = int(MAX_SPEED_KMH * minutes / 60 * 1000 / px) + 1
    lags = np.r_[0 : max_px + 1, -max_px:0]
    sub = cc[np.ix_(lags % shape[0], lags % shape[1])]
    i, j = np.unravel_index(int(np.argmax(sub)), sub.shape)
    return {
        "vx": float(lags[j]) / minutes,
        "vy": float(lags[i]) / minutes,
        "quality": float(sub[i, j]),
    }


def shift_raw(
    raw: np.ndarray, dx: int, dy: int, what: dict[str, Any], clutter: np.ndarray | None
) -> np.ndarray:
    """Move the echo field by (dx, dy) pixels; coverage (nodata) stays put."""
    undetect = int(what.get("undetect", 0))
    nodata = int(what["nodata"]) if "nodata" in what else None
    src = raw.copy()
    if clutter is not None:
        src[clutter] = undetect
    if nodata is not None:
        src[src == nodata] = undetect
    out = np.full_like(raw, undetect)
    h, w = raw.shape
    ys, yd = (
        (slice(0, h - dy), slice(dy, h))
        if dy >= 0
        else (slice(-dy, h), slice(0, h + dy))
    )
    xs, xd = (
        (slice(0, w - dx), slice(dx, w))
        if dx >= 0
        else (slice(-dx, w), slice(0, w + dx))
    )
    out[yd, xd] = src[ys, xs]
    if nodata is not None:
        out[raw == nodata] = nodata
    return out


def nowcast(  # noqa: PLR0913, PLR0917
    state: EchoState,
    prev_raw: np.ndarray | None,
    prev_time: str | None,
    where: dict[str, Any],
    lat: float,
    lon: float,
) -> tuple[dict[str, Any], dict[str, float] | None]:
    """Sensors for the newest frame: rain now, nearest rain, motion, ETA."""
    if state.raw is None:
        return {}, None
    rate = rate_from_raw(state.raw, state.what)
    clutter = state.clutter()
    if clutter is not None:
        rate = np.where(clutter, 0.0, rate)
    col, row, px = to_pixels(where, lat, lon)
    here = local_rate(rate, col, row)
    out: dict[str, Any] = {
        "time": state.time,
        "rain_rate_mmh": None if math.isnan(here) else round(here, 2),
    }

    # Nearest solid rain within 100 km
    rad = int(100_000 / px)
    r, c = round(row), round(col)
    h, w = rate.shape
    r0, r1, c0, c1 = (
        max(0, r - rad),
        min(h, r + rad + 1),
        max(0, c - rad),
        min(w, c + rad + 1),
    )
    win = np.nan_to_num(rate[r0:r1, c0:c1], nan=0.0)
    solid = (win >= RAIN_MMH) & (_neighbours(win >= RAIN_MMH) >= 3)  # noqa: PLR2004
    north = grid_north_deg(where, lat, lon)
    if not math.isnan(here) and here >= RAIN_MMH:
        out.update(nearest_rain_km=0.0, nearest_rain_direction=None)
    elif solid.any():
        yy, xx = np.mgrid[r0:r1, c0:c1]
        d = np.where(solid, np.hypot(xx - col, yy - row) * px / 1000, np.inf)
        k = np.unravel_index(int(np.argmin(d)), d.shape)
        bearing = (math.degrees(math.atan2(xx[k] - col, -(yy[k] - row))) - north) % 360
        out.update(
            nearest_rain_km=round(float(d[k]), 1),
            nearest_rain_direction=COMPASS_DA[round(bearing / 45) % 8],
        )
    else:
        out.update(nearest_rain_km=None, nearest_rain_direction=None)

    # Motion between the two newest frames
    motion = None
    if (
        prev_raw is not None
        and prev_time
        and state.time
        and prev_raw.shape == state.raw.shape
    ):
        minutes = (
            datetime.fromisoformat(state.time) - datetime.fromisoformat(prev_time)
        ).total_seconds() / 60
        if 4 <= minutes <= 30:  # noqa: PLR2004 — consecutive frames only
            prev_rate = rate_from_raw(prev_raw, state.what)
            motion = track(prev_rate, rate, minutes, col, row, px, clutter)
    if motion and motion["quality"] >= MIN_TRACK_QUALITY:
        east, northm = motion["vx"] * px, -motion["vy"] * px  # m per minute
        speed = math.hypot(east, northm) * 60 / 1000
        towards = (math.degrees(math.atan2(east, northm)) - north) % 360
        out.update(
            motion_speed_kmh=round(speed, 1),
            motion_from=COMPASS_DA[round(((towards + 180) % 360) / 45) % 8]
            if speed >= 1
            else None,
            motion_quality=round(motion["quality"], 2),
        )
        # ETA: follow the motion back from the station in 5-min steps, up to 2 h
        eta = None
        for t in range(0, 121, 5):
            pc, pr = col - motion["vx"] * t, row - motion["vy"] * t
            if not (1 <= pc < w - 1 and 1 <= pr < h - 1):
                break
            if local_rate(rate, pc, pr) >= RAIN_MMH:
                eta = t
                break
            if speed < 1:
                break
        out["rain_expected_in_min"] = eta
    else:
        motion = None
        out.update(motion_speed_kmh=None, motion_from=None, rain_expected_in_min=None)
    return out, motion


# ── Main loop ──────────────────────────────────────────────────────────────


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def run(  # noqa: PLR0912, PLR0915
    cfg: configparser.ConfigParser, files: list[Path] | None = None
) -> dict[str, Any]:
    """Fetch, render, prune; return the manifest written to frames.json."""
    r = cfg["radar"]
    out = Path(r["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    bounds = [float(v) for v in r["bounds"].split(",")]
    width = int(r["width_px"])
    keep = timedelta(minutes=int(r["keep_minutes"]))
    min_dbz = float(r["min_dbz"])
    timeout = float(r["timeout_s"])
    lat = cfg.getfloat("radar", "station_lat", fallback=55.7374)
    lon = cfg.getfloat("radar", "station_lon", fallback=12.1659)
    now = datetime.now(UTC)

    grids: dict[str, Grid] = {}
    manifest_path = out / "frames.json"
    try:
        old = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        old = {}
    known = {f["time"]: f for f in old.get("frames", [])}

    sources: list[tuple[datetime | None, bytes]] = []
    if files:
        sources = [(None, p.read_bytes()) for p in files]
    else:
        items = list_frames(r["scan_type"], now - keep, timeout)
        log.info(
            "%d %s frames listed since %s",
            len(items),
            r["scan_type"],
            (now - keep).isoformat(),
        )
        for it in items:
            stamp = it["time"].strftime("%Y-%m-%dT%H:%M:%SZ")
            if stamp in known and (out / Path(known[stamp]["url"]).name).exists():
                continue
            t0 = time.perf_counter()
            sources.append((it["time"], http_get(it["href"], timeout)))
            log.debug("Downloaded %s in %.2fs", it["id"], time.perf_counter() - t0)

    state_dir = Path(r["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    state = EchoState(state_dir / "state.npz")
    prev_raw, prev_time = state.raw, state.time
    last_where: dict[str, Any] | None = None
    last_grid: Grid | None = None
    rendered_any = False

    decoded = []
    for listed_time, blob in sources:
        raw, what, where = read_odim(blob)
        t = listed_time or scan_time(what)
        if t is None:
            log.warning("Skipping a file without scan time")
            continue
        decoded.append((t, raw, what, where))

    # Oldest first, so the echo statistics and "previous frame" stay in order
    for t, raw, what, where in sorted(decoded, key=lambda d: d[0]):
        k = Grid.key(where, raw.shape, bounds, width)
        grid = grids.get(k) or grids.setdefault(
            k, Grid(where, raw.shape, bounds, width)
        )
        stamp = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        name = f"{t.strftime('%Y%m%dT%H%MZ')}.png"
        _write_atomic(out / name, render(raw, what, grid, min_dbz))
        known[stamp] = {"time": stamp, "url": f"/radar/{name}"}
        if state.time is None or stamp > state.time:
            prev_raw, prev_time = state.raw, state.time
            state.add(raw, what, stamp, min_dbz)
            last_where, last_grid = where, grid
            rendered_any = True
        log.info("Rendered %s", name)

    # Prune (keep everything when rendering local files for testing)
    frames = sorted(known.values(), key=lambda f: f["time"])
    if not files:
        cutoff = (now - keep).strftime("%Y-%m-%dT%H:%M:%SZ")
        for f in [f for f in frames if f["time"] < cutoff]:
            with contextlib.suppress(FileNotFoundError):
                (out / Path(f["url"]).name).unlink()
        frames = [f for f in frames if f["time"] >= cutoff]

    # Nowcast + forecast frames — only when a new newest frame arrived
    nowcast_info = old.get("nowcast", {})
    forecast_frames = old.get("forecast", [])
    if (
        rendered_any
        and last_where is not None
        and last_grid is not None
        and state.raw is not None
    ):
        nowcast_info, motion = nowcast(state, prev_raw, prev_time, last_where, lat, lon)
        for f in out.glob("f*.png"):
            f.unlink(missing_ok=True)
        forecast_frames = []
        if motion and cfg.getboolean("radar", "forecast"):
            base = datetime.fromisoformat(state.time)  # type: ignore[arg-type]
            for step in FORECAST_STEPS_MIN:
                dx, dy = round(motion["vx"] * step), round(motion["vy"] * step)
                shifted = shift_raw(state.raw, dx, dy, state.what, state.clutter())
                ft = base + timedelta(minutes=step)
                fname = f"f{base.strftime('%Y%m%dT%H%MZ')}+{step}.png"
                _write_atomic(
                    out / fname, render(shifted, state.what, last_grid, min_dbz)
                )
                forecast_frames.append(
                    {
                        "time": ft.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "url": f"/radar/{fname}",
                    }
                )
            log.info(
                "Nowcast: %s; %d forecast frames", nowcast_info, len(forecast_frames)
            )
        else:
            log.info(
                "Nowcast: %s; no reliable motion → no forecast frames", nowcast_info
            )
        state.save()

    first = next(iter(grids.values()), None)
    manifest = {
        "version": VERSION,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "DMI",
        "scan_type": r["scan_type"],
        # Leaflet order: [[south, west], [north, east]]
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "size": [first.width, first.height] if first else old.get("size"),
        "frames": frames,
        "forecast": forecast_frames,
        "nowcast": nowcast_info,
    }
    _write_atomic(manifest_path, json.dumps(manifest, indent=1).encode())
    return manifest


def load_config(path: Path) -> configparser.ConfigParser:
    """Defaults, overridden by the INI file if it exists (it's optional)."""
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFAULT_CONFIG)
    if path.exists():
        cfg.read(path)
    return cfg


def main() -> None:
    """Entry point."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=Path("/etc/weather-radar.ini"))
    ap.add_argument(
        "--file",
        type=Path,
        nargs="*",
        help="render local .h5 files instead of fetching",
    )
    ap.add_argument("--output-dir", type=Path, help="override [radar] output_dir")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.output_dir:
        cfg["radar"]["output_dir"] = str(args.output_dir)
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"].upper(), logging.INFO),
        format="%(levelname)-8s %(message)s",
    )
    logging.getLogger("pyfive").setLevel(logging.WARNING)  # very chatty at INFO
    if not cfg.getboolean("radar", "enabled"):
        log.info("[radar] enabled = false — exiting")
        return
    try:
        m = run(cfg, args.file)
    except (OSError, ValueError) as err:
        log.error("Radar update failed: %s", err)  # noqa: TRY400 — one line in the journal is enough
        sys.exit(1)
    log.info(
        "%d frames, newest %s",
        len(m["frames"]),
        m["frames"][-1]["time"] if m["frames"] else "-",
    )


if __name__ == "__main__":
    main()
