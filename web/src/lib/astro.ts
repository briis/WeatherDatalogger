// Sun and moon, computed locally with SunCalc — Open-Meteo doesn't report
// moon data, and computing sunrise/sunset locally means those widgets work
// even if the forecast fetch is stale.

import SunCalc from 'suncalc';

/** Station position — Gundsømagle. Override via VITE_LAT / VITE_LON. */
export const STATION = {
  lat: Number(import.meta.env.VITE_LAT ?? 55.7374),
  lon: Number(import.meta.env.VITE_LON ?? 12.1659),
};

export interface SunInfo {
  sunrise: Date;
  sunset: Date;
  solarNoon: Date;
  dawn: Date;
  dusk: Date;
  /** Daylight length in minutes. */
  daylightMin: number;
}

export function sunInfo(date = new Date()): SunInfo {
  const t = SunCalc.getTimes(date, STATION.lat, STATION.lon);
  return {
    sunrise: t.sunrise,
    sunset: t.sunset,
    solarNoon: t.solarNoon,
    dawn: t.dawn,
    dusk: t.dusk,
    daylightMin: Math.round((t.sunset.getTime() - t.sunrise.getTime()) / 60_000),
  };
}

export interface MoonInfo {
  /** 0..1 — 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter. */
  phase: number;
  /** 0..1 illuminated fraction. */
  illumination: number;
  waxing: boolean;
  rise: Date | null;
  set: Date | null;
  nextFull: Date;
  nextNew: Date;
}

const SYNODIC_DAYS = 29.530588853;

/** Step forward from `from` until SunCalc's phase crosses `target`. */
export function nextPhase(from: Date, target: number): Date {
  const start = SunCalc.getMoonIllumination(from).phase;
  let delta = target - start;
  if (delta <= 0.0001) delta += 1;
  const estimate = new Date(from.getTime() + delta * SYNODIC_DAYS * 86_400_000);
  // Refine to the hour with a small local search around the estimate
  let best = estimate;
  let bestErr = Infinity;
  for (let h = -36; h <= 36; h++) {
    const d = new Date(estimate.getTime() + h * 3_600_000);
    const p = SunCalc.getMoonIllumination(d).phase;
    const err = Math.min(Math.abs(p - target), 1 - Math.abs(p - target));
    if (err < bestErr) {
      bestErr = err;
      best = d;
    }
  }
  return best;
}

export function moonInfo(date = new Date()): MoonInfo {
  const ill = SunCalc.getMoonIllumination(date);
  const times = SunCalc.getMoonTimes(date, STATION.lat, STATION.lon);
  return {
    phase: ill.phase,
    illumination: ill.fraction,
    waxing: ill.phase < 0.5,
    rise: times.rise ?? null,
    set: times.set ?? null,
    nextFull: nextPhase(date, 0.5),
    nextNew: nextPhase(date, 0),
  };
}

/** True between sunset and sunrise at the station. */
export function isNight(date = new Date()): boolean {
  const { sunrise, sunset } = sunInfo(date);
  return date < sunrise || date > sunset;
}
