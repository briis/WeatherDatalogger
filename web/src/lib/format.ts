// Danish (da-DK) formatting helpers. Everything renders in Europe/Copenhagen
// regardless of the viewer's device time zone — this is a single-location
// site, and "i dag" must mean the station's day.

import { parseUtc } from '$lib/api/client';

export const TZ = 'Europe/Copenhagen';
export const LOCALE = 'da-DK';
export const DASH = '–';

const nf = (digits: number) =>
  new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const nf0 = nf(0);
const nf1 = nf(1);

type Num = number | null | undefined;
const ok = (v: Num): v is number => typeof v === 'number' && Number.isFinite(v);

/** 3,4 — or "–" for missing values. */
export function num(v: Num, digits = 1): string {
  if (!ok(v)) return DASH;
  return digits === 0 ? nf0.format(v) : digits === 1 ? nf1.format(v) : nf(digits).format(v);
}

/** Apple Weather style rounded temperature: "4°" (and "-0" becomes "0"). */
export function temp(v: Num): string {
  if (!ok(v)) return DASH;
  const r = Math.round(v);
  return `${nf0.format(r === 0 ? 0 : r)}°`;
}

export const pct = (v: Num) => (ok(v) ? `${nf0.format(Math.round(v))} %` : DASH);
export const ms = (v: Num, digits = 0) => (ok(v) ? `${num(v, digits)} m/s` : DASH);
export const hpa = (v: Num) => (ok(v) ? `${nf0.format(Math.round(v))} hPa` : DASH);
export const mm = (v: Num) => (ok(v) ? `${num(v, v > 0 && v < 10 ? 1 : 0)} mm` : DASH);
export const km = (v: Num) => (ok(v) ? `${nf0.format(Math.round(v))} km` : DASH);

const timeFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' });
const hourFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit' });
const weekdayShort = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short' });
const weekdayLong = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'long' });
const dayMonth = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'long' });
const ymd = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });

/** "15.56" — Danish clock uses a period between hours and minutes. */
export const clock = (d: Date | null) => (d ? timeFmt.format(d).replace(':', '.') : DASH);
/** "14" — hour label in the hourly strip. */
export const hour = (d: Date) => hourFmt.format(d);
export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** "Lør" */
export const weekday = (d: Date) => capitalize(weekdayShort.format(d).replace('.', ''));
/** "Lørdag" */
export const weekdayFull = (d: Date) => capitalize(weekdayLong.format(d));
/** "20. november" */
export const dateLong = (d: Date) => dayMonth.format(d);
/** "2026-11-20" in Copenhagen — the key for comparing calendar days. */
export const localDay = (d: Date) => ymd.format(d);

/**
 * forecast_daily.forecast_time is the forecast *day* (provider-reported,
 * naive). Take its date part as a Copenhagen calendar day and anchor it at
 * local noon, so formatting it in TZ can never slip to the neighbouring day.
 */
export function forecastDay(ts: string): Date {
  return new Date(`${ts.slice(0, 10)}T12:00:00+01:00`);
}

/** "I dag" / weekday label for a daily forecast row. */
export function dayLabel(ts: string, now = new Date()): string {
  const d = forecastDay(ts);
  return localDay(d) === localDay(now) ? 'I dag' : weekday(d);
}

/** "for 2 min. siden" style relative time. */
export function ago(d: Date | null, now = new Date()): string {
  if (!d) return DASH;
  const s = Math.max(0, Math.round((now.getTime() - d.getTime()) / 1000));
  if (s < 45) return 'lige nu';
  const m = Math.round(s / 60);
  if (m < 60) return `for ${m} min. siden`;
  const h = Math.round(m / 60);
  if (h < 24) return `for ${h} t. siden`;
  return `for ${Math.round(h / 24)} d. siden`;
}

export { parseUtc };
