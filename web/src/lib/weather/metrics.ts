// One definition per measurement shown in the Vejrforhold popup: where its
// numbers come from (station history for what has happened today, the
// hourly forecast for the rest), how it is charted, and the Danish texts.
//
// Add a metric = one entry here; the popup, chart and menu pick it up.

import type { CombinedRealtime, ForecastHour, HistoryRow } from '$lib/api/types';
import { PRESSURE_TREND, compass, uvLevel } from '$lib/i18n/da';
import { clock, num, temp } from '$lib/format';

export type MetricId =
  | 'temp'
  | 'feels'
  | 'precip'
  | 'wind'
  | 'humidity'
  | 'pressure'
  | 'uv'
  | 'visibility'
  | 'solar';

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
  /** when the primary series peaks (unix s), e.g. for UV */
  maxAt: number | null;
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
  /** Fixed y-range floor (e.g. 0 for wind/rain) / ceiling (100 % humidity) */
  yMin?: number;
  yMax?: number;
  /** Smallest y-span shown (keeps a flat pressure day from looking dramatic) */
  minSpan?: number;
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
      'Temperaturen måles af din egen station 2 m over jorden. Kurven viser målingerne indtil nu og derefter prognosen fra Open-Meteo, der de første timer justeres mod det, stationen måler. Dagens højeste og laveste tager både det målte og det ventede med.',
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
  humidity: {
    id: 'humidity',
    label: 'Luftfugtighed',
    unit: '%',
    kind: 'line',
    yMin: 0,
    yMax: 100,
    series: [{ label: 'Luftfugtighed', color: '#5ac8fa', history: 'relative_humidity_pct', forecast: 'humidity_pct' }],
    format: (v) => (v == null ? '–' : `${num(v, 0)} %`),
    headline: (d) => ({
      big: d.isToday
        ? `${num(d.now?.relative_humidity_pct ?? d.hour?.humidity_pct, 0)} %`
        : `${num(d.hour?.humidity_pct, 0)} %`,
      sub: `Dugpunkt ${temp(d.isToday ? (d.now?.dew_point_c ?? d.hour?.dew_point_c) : d.hour?.dew_point_c)}`,
    }),
    summary: (d) => {
      const dp = d.isToday ? d.now?.dew_point_c : d.hour?.dew_point_c;
      const feel =
        dp == null ? '' : dp < 10 ? ' Det føles ikke fugtigt.' : dp < 16 ? ' Det føles behageligt.' : dp < 20 ? ' Det føles lidt fugtigt.' : ' Det føles trykkende fugtigt.';
      return d.isToday
        ? `Luftfugtigheden er ${num(d.now?.relative_humidity_pct, 0)} % lige nu, og dugpunktet er ${temp(dp)}.${feel} I dag mellem ${num(d.min, 0)} og ${num(d.max, 0)} %.`
        : `${d.title}: luftfugtighed mellem ${num(d.min, 0)} og ${num(d.max, 0)} %, dugpunkt omkring ${temp(dp)}.${feel}`;
    },
    about:
      'Relativ luftfugtighed er, hvor meget vanddamp luften indeholder i forhold til det maksimale ved den aktuelle temperatur. Dugpunktet er den temperatur, luften skal køles ned til, før der dannes dug eller tåge — det siger mere om, hvor fugtigt det føles, end procenten gør.',
  },
  pressure: {
    id: 'pressure',
    label: 'Lufttryk',
    unit: 'hPa',
    kind: 'line',
    minSpan: 10,
    series: [{ label: 'Lufttryk', color: '#bf9cff', history: 'sea_level_pressure_mb', forecast: 'pressure_mb' }],
    format: (v) => (v == null ? '–' : `${num(v, 0)} hPa`),
    headline: (d) => {
      const trend = d.now?.sea_level_pressure_trend ?? d.now?.pressure_trend ?? null;
      return {
        big: `${num(d.isToday ? (d.now?.sea_level_pressure_mb ?? d.hour?.pressure_mb) : d.hour?.pressure_mb, 0)} hPa`,
        sub: d.isToday && trend ? `${PRESSURE_TREND[trend] ?? trend}` : `${num(d.min, 0)}–${num(d.max, 0)} hPa`,
      };
    },
    summary: (d) => {
      const delta = d.now?.sea_level_pressure_trend_mb ?? d.now?.pressure_trend_mb ?? null;
      const trend =
        delta == null
          ? ''
          : Math.abs(delta) < 1
            ? ' Det har været stabilt de seneste 3 timer.'
            : delta > 0
              ? ` Det er steget ${num(delta, 1)} hPa på 3 timer — ofte et tegn på mere stabilt vejr.`
              : ` Det er faldet ${num(-delta, 1)} hPa på 3 timer — ofte et tegn på skyer, regn eller vind.`;
      return d.isToday
        ? `Lufttrykket er ${num(d.now?.sea_level_pressure_mb, 0)} hPa lige nu.${trend}`
        : `${d.title}: lufttryk mellem ${num(d.min, 0)} og ${num(d.max, 0)} hPa.`;
    },
    about:
      'Lufttrykket er omregnet til havniveau, så det kan sammenlignes med andre stationer og vejrkort. Normalt tryk er omkring 1013 hPa. Højtryk giver typisk stille og tørt vejr, lavtryk skyer, regn og blæst. Hurtige fald er et varsel om dårligere vejr.',
  },
  uv: {
    id: 'uv',
    label: 'UV-indeks',
    unit: '',
    kind: 'line',
    yMin: 0,
    minSpan: 4,
    series: [{ label: 'UV-indeks', color: 'uv', history: 'uv_index', forecast: 'uv_index' }],
    format: (v) => (v == null ? '–' : num(v, 0)),
    headline: (d) => {
      const uv = d.isToday ? (d.now?.uv_index ?? d.hour?.uv_index ?? null) : d.max;
      return {
        big: `${num(uv, 0)} ${uvLevel(uv)}`,
        sub:
          d.max != null && d.maxAt != null
            ? `Højest ${num(d.max, 0)} (${uvLevel(d.max).toLowerCase()}) kl. ${clock(new Date(d.maxAt * 1000))}`
            : '',
      };
    },
    summary: (d) => {
      const peak = d.max ?? 0;
      const when = d.maxAt != null ? ` omkring kl. ${clock(new Date(d.maxAt * 1000))}` : '';
      const advice =
        peak >= 3
          ? ' Brug solbeskyttelse, når du er ude midt på dagen.'
          : ' Det er ikke nødvendigt med solbeskyttelse.';
      return `${d.isToday ? 'I dag' : d.title} når UV-indekset ${num(peak, 0)} (${uvLevel(peak).toLowerCase()})${when}.${advice}`;
    },
    about:
      'UV-indekset angiver styrken af solens ultraviolette stråling, der kan give solskoldning. 0–2 er lav, 3–5 moderat, 6–7 høj, 8–10 meget høj og 11+ ekstrem. Fra 3 og op anbefales solcreme, solbriller og skygge midt på dagen. Målt af din Tempest indtil nu.',
  },
  visibility: {
    id: 'visibility',
    label: 'Sigtbarhed',
    unit: 'km',
    kind: 'line',
    yMin: 0,
    minSpan: 10,
    series: [{ label: 'Sigtbarhed', color: '#d1d9e6', history: null, forecast: 'visibility_km' }],
    format: (v) => (v == null ? '–' : `${num(v, 0)} km`),
    headline: (d) => ({
      big: `${num(d.hour?.visibility_km, 0)} km`,
      sub: d.min != null ? `Laveste ${num(d.min, 0)} km` : '',
    }),
    summary: (d) => {
      const v = d.hour?.visibility_km ?? null;
      const word =
        v == null ? 'ukendt' : v >= 20 ? 'helt klart' : v >= 10 ? 'godt' : v >= 4 ? 'let diset' : v >= 1 ? 'diset' : 'tåget';
      return `${d.isToday ? 'Udsynet er' : `${d.title}: udsynet ventes`} ${word} (${num(v, 0)} km)${
        d.min != null && d.min < 1 ? '. Der kan komme tåge i løbet af dagen.' : '.'
      }`;
    },
    about:
      'Sigtbarhed er, hvor langt man kan se ved dagslys. Den sænkes af tåge, dis, nedbør og røg. Under 1 km kaldes tåge. Din station måler ikke sigtbarhed, så kurven er Open-Meteos prognose.',
  },
  solar: {
    id: 'solar',
    label: 'Solstråling',
    unit: 'W/m²',
    kind: 'line',
    yMin: 0,
    minSpan: 100,
    series: [{ label: 'Solstråling', color: '#ffd60a', history: 'solar_radiation_wm2', forecast: 'solar_radiation_wm2' }],
    format: (v) => (v == null ? '–' : `${num(v, 0)} W/m²`),
    headline: (d) => ({
      big: `${num(d.isToday ? (d.now?.solar_radiation_wm2 ?? d.hour?.solar_radiation_wm2) : d.max, 0)} W/m²`,
      sub:
        d.max != null && d.maxAt != null
          ? `Højest ${num(d.max, 0)} W/m² kl. ${clock(new Date(d.maxAt * 1000))}`
          : '',
    }),
    summary: (d) =>
      (d.max ?? 0) < 1
        ? `${d.isToday ? 'I dag' : d.title}: ingen nævneværdig solstråling.`
        : `${d.isToday ? 'I dag' : d.title} topper solstrålingen med ${num(d.max, 0)} W/m²${
            d.maxAt != null ? ` omkring kl. ${clock(new Date(d.maxAt * 1000))}` : ''
          }. En klar sommerdag i Danmark når op omkring 800–900 W/m².`,
    about:
      'Solstråling (globalstråling) er den samlede energi fra solen, der rammer en vandret flade — direkte sol plus lys fra himlen. Skyer kan halvere den på få minutter. Målt af din Tempest indtil nu, derefter prognosen.',
  },
};

export const METRIC_ORDER: MetricId[] = [
  'temp',
  'feels',
  'precip',
  'wind',
  'humidity',
  'pressure',
  'uv',
  'solar',
  'visibility',
];
