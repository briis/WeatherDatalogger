// One definition per measurement shown in the Vejrforhold popup: where its
// numbers come from (station history for what has happened today, the
// hourly forecast for the rest), how it is charted, and the Danish texts.
//
// Add a metric = one entry here; the popup, chart and menu pick it up.

import type { CombinedRealtime, ForecastHour, HistoryRow } from '$lib/api/types';
import { compass } from '$lib/i18n/da';
import { num, temp } from '$lib/format';

export type MetricId = 'temp' | 'feels' | 'precip' | 'wind';

export interface Series {
  label: string;
  /** colour for the line / bars */
  color: string;
  /** history_charting column, or null if the station doesn't measure it */
  history: keyof CombinedRealtime | null;
  /** forecast_hourly column */
  forecast: keyof ForecastHour;
  dashed?: boolean;
}

export interface DayStats {
  isToday: boolean;
  /** Short weekday + date, e.g. "Fredag 20. november" */
  title: string;
  now: CombinedRealtime | null;
  min: number | null;
  max: number | null;
  /** extra numbers a metric may want (e.g. total precipitation) */
  total: number | null;
  /** forecast row for "now" or noon on other days */
  hour: ForecastHour | null;
}

export interface Metric {
  id: MetricId;
  label: string;
  unit: string;
  kind: 'line' | 'bars';
  series: Series[];
  /** Fixed y-range floor (e.g. 0 for wind/rain) */
  yMin?: number;
  /** History rows → values (e.g. cumulative rain → per-hour) */
  fromHistory?: (rows: HistoryRow[], field: keyof CombinedRealtime) => [number[], (number | null)[]];
  format: (v: number | null) => string;
  /** The big number + subline at the top of the popup */
  headline: (d: DayStats) => { big: string; sub: string };
  summary: (d: DayStats) => string;
  about: string;
  /** Show wind-direction arrows above the chart */
  arrows?: boolean;
}

/** Turn the cumulative "rain so far today" counter into per-hour amounts. */
function hourlyFromCumulative(rows: HistoryRow[], field: keyof CombinedRealtime): [number[], (number | null)[]] {
  const xs: number[] = [];
  const ys: (number | null)[] = [];
  let bucket = -1;
  let startVal = 0;
  let lastVal = 0;
  for (const r of rows) {
    const t = Date.parse(`${r.window_start}Z`) / 1000;
    const v = typeof r[field] === 'number' ? (r[field] as number) : null;
    if (v == null) continue;
    const h = Math.floor(t / 3600) * 3600;
    if (h !== bucket) {
      if (bucket >= 0) {
        xs.push(bucket + 1800);
        ys.push(Math.max(0, lastVal - startVal));
      }
      // counter resets at local midnight → never go negative
      startVal = v < lastVal ? 0 : lastVal;
      bucket = h;
    }
    lastVal = v;
  }
  if (bucket >= 0) {
    xs.push(bucket + 1800);
    ys.push(Math.max(0, lastVal - startVal));
  }
  return [xs, ys];
}

const deg = (v: number | null) => temp(v);

export const METRICS: Record<MetricId, Metric> = {
  temp: {
    id: 'temp',
    label: 'Temperatur',
    unit: '°C',
    kind: 'line',
    series: [{ label: 'Temperatur', color: 'temp', history: 'air_temperature_c', forecast: 'temperature_c' }],
    format: deg,
    headline: (d) => ({
      big: d.isToday ? temp(d.now?.air_temperature_c ?? d.hour?.temperature_c) : temp(d.max),
      sub: `H: ${temp(d.max)}  L: ${temp(d.min)}`,
    }),
    summary: (d) =>
      d.isToday
        ? `Temperaturen er ${temp(d.now?.air_temperature_c)} lige nu. I dag ligger den mellem ${temp(d.min)} og ${temp(d.max)}.`
        : `${d.title}: temperaturen ventes mellem ${temp(d.min)} og ${temp(d.max)}.`,
    about:
      'Temperaturen måles af din egen station 2 m over jorden. Kurven viser målingerne indtil nu og derefter prognosen fra Open-Meteo. Dagens højeste og laveste tager både det målte og det ventede med.',
  },
  feels: {
    id: 'feels',
    label: 'Føles som',
    unit: '°C',
    kind: 'line',
    series: [
      { label: 'Føles som', color: 'temp', history: 'feels_like_c', forecast: 'feels_like_c' },
      { label: 'Temperatur', color: 'rgb(255 255 255 / 0.45)', history: 'air_temperature_c', forecast: 'temperature_c', dashed: true },
    ],
    format: deg,
    headline: (d) => ({
      big: d.isToday ? temp(d.now?.feels_like_c ?? d.hour?.feels_like_c) : temp(d.max),
      sub: d.isToday ? `Faktisk: ${temp(d.now?.air_temperature_c)}` : `H: ${temp(d.max)}  L: ${temp(d.min)}`,
    }),
    summary: (d) =>
      d.isToday
        ? `Det føles som ${temp(d.now?.feels_like_c)} lige nu, mod en faktisk temperatur på ${temp(d.now?.air_temperature_c)}.`
        : `${d.title}: det ventes at føles som mellem ${temp(d.min)} og ${temp(d.max)}.`,
    about:
      'Føles som tager højde for vind og luftfugtighed. Vind køler huden (vindafkøling), og høj luftfugtighed om sommeren får varmen til at føles kraftigere (varmeindeks). Den stiplede linje er den faktiske temperatur.',
  },
  precip: {
    id: 'precip',
    label: 'Nedbør',
    unit: 'mm',
    kind: 'bars',
    yMin: 0,
    series: [{ label: 'Nedbør', color: '#64b5ff', history: 'rain_accumulation_mm', forecast: 'precipitation_mm' }],
    fromHistory: hourlyFromCumulative,
    format: (v) => (v == null ? '–' : `${num(v, v > 0 && v < 10 ? 1 : 0)} mm`),
    headline: (d) => ({
      big: `${num(d.total ?? 0, (d.total ?? 0) > 0 && (d.total ?? 0) < 10 ? 1 : 0)} mm`,
      sub: d.isToday ? 'I alt i dag' : 'Ventet i alt',
    }),
    summary: (d) =>
      (d.total ?? 0) < 0.1
        ? d.isToday
          ? 'Ingen nedbør i dag indtil videre, og der ventes ingen resten af dagen.'
          : `${d.title}: ingen nedbør ventet.`
        : d.isToday
          ? `${num(d.total, 1)} mm i alt i dag, målt af stationen indtil nu og ventet resten af dagen.`
          : `${d.title}: ${num(d.total, 1)} mm ventet.`,
    about:
      'Søjlerne viser nedbør pr. time. Indtil nu er det din regnmålers målinger, derefter Open-Meteos prognose. Sne måles som smeltet vand, så 1 mm svarer til omkring 1 cm sne.',
  },
  wind: {
    id: 'wind',
    label: 'Vind',
    unit: 'm/s',
    kind: 'line',
    yMin: 0,
    arrows: true,
    series: [
      { label: 'Vind', color: '#8fd3ff', history: 'wind_avg_ms', forecast: 'wind_speed_ms' },
      { label: 'Vindstød', color: 'rgb(255 255 255 / 0.55)', history: 'wind_gust_ms', forecast: 'wind_gust_ms', dashed: true },
    ],
    format: (v) => (v == null ? '–' : `${num(v, 0)} m/s`),
    headline: (d) => ({
      big: d.isToday ? `${num(d.now?.wind_avg_ms ?? d.hour?.wind_speed_ms, 0)} m/s` : `${num(d.max, 0)} m/s`,
      sub: d.isToday
        ? `Vindstød ${num(d.now?.wind_gust_ms, 0)} m/s · ${compass(d.now?.wind_direction_deg)}`
        : `Vindstød op til ${num(d.total, 0)} m/s`,
    }),
    summary: (d) =>
      d.isToday
        ? `Vinden er ${num(d.now?.wind_avg_ms, 0)} m/s fra ${compass(d.now?.wind_direction_deg)} med vindstød op til ${num(d.now?.wind_gust_ms, 0)} m/s. I dag op til ${num(d.max, 0)} m/s, stød op til ${num(d.total, 0)} m/s.`
        : `${d.title}: vind op til ${num(d.max, 0)} m/s med stød op til ${num(d.total, 0)} m/s.`,
    about:
      'Vindhastigheden er et gennemsnit, vindstød er de kraftigste kortvarige pust. Pilene viser, hvor vinden blæser hen — den kommer fra den modsatte retning. Målt af din station indtil nu, derefter prognosen.',
  },
};

export const METRIC_ORDER: MetricId[] = ['temp', 'feels', 'precip', 'wind'];
