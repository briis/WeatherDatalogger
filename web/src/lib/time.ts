// Calendar-day helpers in Europe/Copenhagen, independent of the viewer's
// device time zone.

import { localDay } from '$lib/format';

/** UTC instant of local midnight for a "YYYY-MM-DD" Copenhagen day. */
export function cphMidnight(dayKey: string): Date {
  for (const off of ['+01:00', '+02:00']) {
    const d = new Date(`${dayKey}T00:00:00${off}`);
    const hh = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Copenhagen',
      hour: '2-digit',
      hourCycle: 'h23',
    }).format(d);
    if (localDay(d) === dayKey && hh === '00') return d;
  }
  return new Date(`${dayKey}T00:00:00+01:00`);
}

/** [start, end) of a Copenhagen day as UTC instants (handles 23/25 h DST days). */
export function dayRange(dayKey: string): [Date, Date] {
  const start = cphMidnight(dayKey);
  const next = localDay(new Date(start.getTime() + 26 * 3_600_000));
  return [start, cphMidnight(next)];
}

/** The next `n` Copenhagen day keys starting with today. */
export function nextDays(n: number, now = new Date()): string[] {
  const out: string[] = [];
  let t = cphMidnight(localDay(now)).getTime() + 12 * 3_600_000;
  for (let i = 0; i < n; i++, t += 86_400_000) out.push(localDay(new Date(t)));
  return out;
}

/** Noon of a day key — safe to format as that day in any time zone logic. */
export const dayNoon = (dayKey: string) => new Date(cphMidnight(dayKey).getTime() + 12 * 3_600_000);
