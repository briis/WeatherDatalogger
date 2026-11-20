// Builds the hourly strip: "Nu" (station reading), then forecast hours, with
// sunrise/sunset inserted at their exact minute — like Apple Weather.

import SunCalc from 'suncalc';
import { parseUtc } from '$lib/api/client';
import type { CombinedRealtime, ForecastHour, WeatherCondition } from '$lib/api/types';
import { STATION } from '$lib/astro';

export type HourPoint = {
      kind: 'now' | 'hour';
      time: Date;
      temp: number | null;
      condition: WeatherCondition | null;
      night: boolean;
      pop: number | null;
      mm: number | null;
      wind: number | null;
      gust: number | null;
      bearing: number | null;
    };
export type SunEvent = { kind: 'sunrise' | 'sunset'; time: Date };
export type HourItem = HourPoint | SunEvent;

export function isNightAt(d: Date): boolean {
  const t = SunCalc.getTimes(d, STATION.lat, STATION.lon);
  return d < t.sunrise || d > t.sunset;
}

export function buildHourly(
  hours: ForecastHour[],
  now: Date,
  current: CombinedRealtime | null,
  nowCondition: WeatherCondition | null,
  count = 24,
): HourItem[] {
  const parsed = hours
    .map((h) => ({ h, t: parseUtc(h.forecast_time) }))
    .filter((x): x is { h: ForecastHour; t: Date } => x.t != null);
  // The hour bucket we're in (forecast_time <= now < +1h) supplies "Nu"'s fallbacks
  const curIdx = parsed.findIndex((x) => x.t.getTime() > now.getTime()) - 1;
  const cur = curIdx >= 0 ? parsed[curIdx]?.h : undefined;
  const future = parsed.filter((x) => x.t.getTime() > now.getTime()).slice(0, count);

  const items: HourItem[] = [
    {
      kind: 'now',
      time: now,
      temp: current?.air_temperature_c ?? cur?.temperature_c ?? null,
      condition: nowCondition ?? cur?.weather_condition ?? null,
      night: isNightAt(now),
      pop: cur?.precipitation_probability_pct ?? null,
      mm: current?.rain_rate_mmh ?? cur?.precipitation_mm ?? null,
      wind: current?.wind_avg_ms ?? cur?.wind_speed_ms ?? null,
      gust: current?.wind_gust_ms ?? cur?.wind_gust_ms ?? null,
      bearing: current?.wind_direction_deg ?? cur?.wind_bearing_deg ?? null,
    },
    ...future.map(
      ({ h, t }): HourItem => ({
        kind: 'hour',
        time: t,
        temp: h.temperature_c,
        condition: h.weather_condition,
        night: isNightAt(t),
        pop: h.precipitation_probability_pct,
        mm: h.precipitation_mm,
        wind: h.wind_speed_ms,
        gust: h.wind_gust_ms,
        bearing: h.wind_bearing_deg,
      }),
    ),
  ];

  const end = future.at(-1)?.t ?? now;
  const events: HourItem[] = [];
  for (const day of [now, new Date(now.getTime() + 86_400_000)]) {
    const t = SunCalc.getTimes(day, STATION.lat, STATION.lon);
    for (const [kind, d] of [
      ['sunrise', t.sunrise],
      ['sunset', t.sunset],
    ] as const) {
      if (d > now && d < end) events.push({ kind, time: d });
    }
  }
  return [...items, ...events].sort((a, b) => a.time.getTime() - b.time.getTime());
}
