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

VERSION = "0.1.0"
BASE = "https://opendataapi.dmi.dk/v1/radardata"
UA = f"weatherdatalogger-web-radar/{VERSION} (+https://github.com/briis/WeatherDatalogger)"

DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "radar": {
        "enabled": "true",
        "scan_type": "doppler",  # doppler | fullRange
        "keep_minutes": "120",
        "output_dir": "/var/lib/weather-web/radar",
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


def rain_at(
    raw: np.ndarray, what: dict[str, Any], where: dict[str, Any], lat: float, lon: float
) -> float | None:
    """mm/h at a point: mean of 3x3 pixels (1.5 km), Marshall-Palmer Z=200R^1.6."""
    x, y = stere_xy(where["projdef"], np.array(lat), np.array(lon))
    ul_x, ul_y = stere_xy(
        where["projdef"],
        np.array(float(where["UL_lat"])),
        np.array(float(where["UL_lon"])),
    )
    c = int((float(x) - float(ul_x)) / float(where["xscale"]))
    r = int((float(ul_y) - float(y)) / float(where["yscale"]))
    if not (1 <= r < raw.shape[0] - 1 and 1 <= c < raw.shape[1] - 1):
        return None
    win = raw[r - 1 : r + 2, c - 1 : c + 2].astype(np.float64)
    gain, offset = float(what.get("gain", 1.0)), float(what.get("offset", 0.0))
    nodata, undetect = what.get("nodata"), what.get("undetect")
    rates = []
    for v in win.ravel():
        if nodata is not None and v == nodata:
            continue
        if undetect is not None and v == undetect:
            rates.append(0.0)
            continue
        dbz = v * gain + offset
        rates.append(0.0 if dbz < 7 else (10 ** (dbz / 10) / 200) ** (1 / 1.6))  # noqa: PLR2004
    return round(sum(rates) / len(rates), 2) if rates else None


# ── Main loop ──────────────────────────────────────────────────────────────


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def run(
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

    latest_rain: tuple[str, float | None] | None = None
    for listed_time, blob in sources:
        raw, what, where = read_odim(blob)
        t = listed_time or scan_time(what)
        if t is None:
            log.warning("Skipping a file without scan time")
            continue
        k = Grid.key(where, raw.shape, bounds, width)
        grid = grids.get(k) or grids.setdefault(
            k, Grid(where, raw.shape, bounds, width)
        )
        stamp = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        name = f"{t.strftime('%Y%m%dT%H%MZ')}.png"
        _write_atomic(out / name, render(raw, what, grid, min_dbz))
        known[stamp] = {"time": stamp, "url": f"/radar/{name}"}
        if latest_rain is None or stamp > latest_rain[0]:
            latest_rain = (stamp, rain_at(raw, what, where, lat, lon))
        log.info("Rendered %s", name)

    # Prune (keep everything when rendering local files for testing)
    frames = sorted(known.values(), key=lambda f: f["time"])
    if not files:
        cutoff = (now - keep).strftime("%Y-%m-%dT%H:%M:%SZ")
        for f in [f for f in frames if f["time"] < cutoff]:
            with contextlib.suppress(FileNotFoundError):
                (out / Path(f["url"]).name).unlink()
        frames = [f for f in frames if f["time"] >= cutoff]

    nowcast = old.get("nowcast", {})
    if latest_rain and frames and latest_rain[0] == frames[-1]["time"]:
        nowcast = {"time": latest_rain[0], "rain_rate_mmh": latest_rain[1]}

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
        "nowcast": nowcast,
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
