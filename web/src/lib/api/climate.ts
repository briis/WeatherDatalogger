// Climate normal for "Gennemsnit": the mean daily high for this calendar day
// (±7 days) over 1991–2020, from Open-Meteo's historical archive (ERA5).
//
// The station's own history only starts mid-2026 — far too short for a
// normal — so this is fetched straight from the browser (Open-Meteo is
// CORS-enabled and free for non-commercial use). The whole 30-year series
// is ~11k values; it's reduced to a 366-entry day-of-year table and cached
// in localStorage, so the archive is hit at most once per browser.

import { STATION } from '$lib/astro';

const CACHE_KEY = 'wdl.climate.v1';
const START = 1991;
const END = 2020;
const WINDOW_DAYS = 7;

interface Normals {
  lat: number;
  lon: number;
  /** index 0..365 = day of year (leap-year indexed), mean daily max °C */
  tmax: number[];
}

const doy = (d: Date) => {
  // Leap-year-indexed day of year, so 29 Feb has its own slot
  const m = d.getMonth();
  const days = [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
  return (days[m] ?? 0) + d.getDate() - 1;
};

function load(): Normals | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const n = JSON.parse(raw) as Normals;
    return Math.abs(n.lat - STATION.lat) < 0.05 && Math.abs(n.lon - STATION.lon) < 0.05 && n.tmax.length === 366
      ? n
      : null;
  } catch {
    return null;
  }
}

let inflight: Promise<Normals> | null = null;

async function fetchNormals(): Promise<Normals> {
  const url =
    `https://archive-api.open-meteo.com/v1/archive?latitude=${STATION.lat}&longitude=${STATION.lon}` +
    `&start_date=${START}-01-01&end_date=${END}-12-31&daily=temperature_2m_max&timezone=Europe%2FCopenhagen`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Open-Meteo archive ${res.status}`);
  const j = (await res.json()) as { daily: { time: string[]; temperature_2m_max: (number | null)[] } };
  const sum = new Array<number>(366).fill(0);
  const cnt = new Array<number>(366).fill(0);
  j.daily.time.forEach((t, i) => {
    const v = j.daily.temperature_2m_max[i];
    if (v == null) return;
    const k = doy(new Date(`${t}T12:00:00`));
    sum[k]! += v;
    cnt[k]! += 1;
  });
  const daily = sum.map((s, i) => (cnt[i] ? s / cnt[i]! : NaN));
  // Smooth with a ±WINDOW_DAYS circular window
  const tmax = daily.map((_, i) => {
    let s = 0;
    let n = 0;
    for (let k = -WINDOW_DAYS; k <= WINDOW_DAYS; k++) {
      const v = daily[(i + k + 366) % 366]!;
      if (!Number.isNaN(v)) {
        s += v;
        n++;
      }
    }
    return n ? Math.round((s / n) * 10) / 10 : NaN;
  });
  const normals = { lat: STATION.lat, lon: STATION.lon, tmax };
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(normals));
  } catch {
    /* storage full/blocked — just refetch next time */
  }
  return normals;
}

/** Mean daily high (°C) for `date`'s calendar day, 1991–2020. */
export async function normalHigh(date = new Date()): Promise<number | null> {
  const cached = load();
  const n = cached ?? (await (inflight ??= fetchNormals().finally(() => (inflight = null))));
  const v = n.tmax[doy(date)];
  return v == null || Number.isNaN(v) ? null : v;
}

export const NORMAL_PERIOD = `${START}–${END}`;
