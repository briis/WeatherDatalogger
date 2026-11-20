// The "scene": what the sky should look like right now.
//
// Condition = the forecast's condition, overridden by what the station
// actually observes (it's raining *now* if the rain gauge says so, no matter
// what the model predicted), plus day/night/twilight from the sun's position.
//
// For previewing every look without waiting for the weather, append e.g.
//   ?sky=rainy            any WeatherCondition
//   ?sky=snowy&tod=night  tod = day | night | dawn | dusk
// to the URL.

import SunCalc from 'suncalc';
import type { CombinedRealtime, ForecastCurrent, WeatherCondition } from '$lib/api/types';
import { parseUtc } from '$lib/api/client';
import { STATION } from '$lib/astro';
import { forecast, live } from '$lib/stores/weather.svelte';

export type TimeOfDay = 'day' | 'night' | 'dawn' | 'dusk';

/** Coarse look families shared by the sky gradient and the effects layer. */
export type SkyFamily = 'clear' | 'partly' | 'cloudy' | 'rain' | 'snow' | 'fog' | 'storm';

const RAIN_MMH = 0.2; // below this a Davis tipping bucket is noise/drizzle remnant
const POURING_MMH = 7.6; // WMO "heavy rain"
const LIGHTNING_RECENT_MIN = 15;
const WINDY_MS = 10.8; // Beaufort 6 ("Hård vind")

/** Merge station observations into the forecast's condition. */
export function effectiveCondition(
  f: ForecastCurrent | null,
  c: CombinedRealtime | null,
  night: boolean,
  now = new Date(),
): WeatherCondition | null {
  let cond = f?.weather_condition ?? null;
  const rate = c?.rain_rate_mmh ?? 0;
  const temp = c?.air_temperature_c ?? f?.temperature_c ?? null;
  const strike = parseUtc(c?.lightning_last_detected);
  const recentStrike =
    strike != null && now.getTime() - strike.getTime() < LIGHTNING_RECENT_MIN * 60_000;

  if (rate >= RAIN_MMH) {
    const frozen = temp != null && temp <= 0.5;
    cond = recentStrike
      ? 'lightning-rainy'
      : frozen
        ? 'snowy'
        : temp != null && temp <= 2
          ? 'snowy-rainy'
          : rate >= POURING_MMH
            ? 'pouring'
            : 'rainy';
  } else if (recentStrike) {
    cond = 'lightning';
  } else if (
    (c?.wind_avg_ms ?? 0) >= WINDY_MS &&
    (cond === 'sunny' || cond === 'partlycloudy' || cond === 'clear-night')
  ) {
    cond = 'windy';
  }

  if (night && cond === 'sunny') cond = 'clear-night';
  if (!night && cond === 'clear-night') cond = 'sunny';
  return cond;
}

export function family(c: WeatherCondition | null): SkyFamily {
  switch (c) {
    case 'partlycloudy':
    case 'windy':
      return 'partly';
    case 'cloudy':
    case 'windy-variant':
      return 'cloudy';
    case 'rainy':
    case 'pouring':
    case 'snowy-rainy':
      return c === 'snowy-rainy' ? 'snow' : 'rain';
    case 'snowy':
    case 'hail':
      return 'snow';
    case 'fog':
      return 'fog';
    case 'lightning':
    case 'lightning-rainy':
      return 'storm';
    default:
      return 'clear';
  }
}

const TWILIGHT_MIN = 45;

export function timeOfDay(now = new Date()): TimeOfDay {
  const t = SunCalc.getTimes(now, STATION.lat, STATION.lon);
  const ms = now.getTime();
  const near = (d: Date) => Math.abs(ms - d.getTime()) < TWILIGHT_MIN * 60_000;
  if (near(t.sunrise)) return 'dawn';
  if (near(t.sunset)) return 'dusk';
  return ms > t.sunrise.getTime() && ms < t.sunset.getTime() ? 'day' : 'night';
}

const CONDITIONS = new Set<string>([
  'clear-night', 'cloudy', 'exceptional', 'fog', 'hail', 'lightning', 'lightning-rainy',
  'partlycloudy', 'pouring', 'rainy', 'snowy', 'snowy-rainy', 'sunny', 'windy', 'windy-variant',
]);

function previewOverride(): { sky: WeatherCondition | null; tod: TimeOfDay | null } {
  if (typeof location === 'undefined') return { sky: null, tod: null };
  const q = new URLSearchParams(location.search);
  const sky = q.get('sky');
  const tod = q.get('tod');
  return {
    sky: sky && CONDITIONS.has(sky) ? (sky as WeatherCondition) : null,
    tod: tod === 'day' || tod === 'night' || tod === 'dawn' || tod === 'dusk' ? tod : null,
  };
}

class SceneStore {
  now = $state(new Date());
  readonly preview = previewOverride();

  constructor() {
    if (typeof window === 'undefined') return;
    setInterval(() => (this.now = new Date()), 60_000);
  }

  tod = $derived<TimeOfDay>(this.preview.tod ?? timeOfDay(this.now));
  night = $derived(this.tod === 'night');

  condition = $derived<WeatherCondition | null>(
    this.preview.sky ??
      effectiveCondition(forecast.current, live.current, this.tod === 'night', this.now),
  );

  family = $derived<SkyFamily>(family(this.condition));
}

export const scene = new SceneStore();
