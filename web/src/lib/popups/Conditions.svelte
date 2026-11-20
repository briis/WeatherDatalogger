<!--
  Vejrforhold — the shared Apple-style detail sheet.

  Day picker (10 days) → headline (big value, condition, H/L) → metric menu
  → day chart (station measurements until now, forecast after) → summary
  sentence → "Om …" explanation. Each widget opens it with its own metric
  preselected; the 10-day widget opens it on the tapped day (ui.param).
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import { parseUtc, api } from '$lib/api/client';
  import type { CombinedRealtime, ForecastHour, HistoryRow } from '$lib/api/types';
  import Chart, { type ChartSeries } from '$lib/components/Chart.svelte';
  import WeatherIcon from '$lib/components/WeatherIcon.svelte';
  import { clock, forecastDay, localDay, weekdayFull, dateLong } from '$lib/format';
  import { conditionText } from '$lib/i18n/da';
  import { cachedLoad, forecast, live } from '$lib/stores/weather.svelte';
  import { ui } from '$lib/stores/ui.svelte';
  import { dayNoon, dayRange, nextDays } from '$lib/time';
  import { METRICS, METRIC_ORDER, type MetricId, type DayStats } from '$lib/weather/metrics';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';
  import DayPicker from './DayPicker.svelte';

  let { def }: { def: WidgetDef } = $props();

  const INITIAL: Partial<Record<string, MetricId>> = {
    hourly: 'temp',
    daily: 'temp',
    wind: 'wind',
    feelslike: 'feels',
    precipitation: 'precip',
    humidity: 'humidity',
    pressure: 'pressure',
    uv: 'uv',
    visibility: 'visibility',
    solar: 'solar',
  };
  // Starting metric only — the menu changes it afterwards
  let metricId = $state<MetricId>(untrack(() => INITIAL[def.id] ?? 'temp'));
  const metric = $derived(METRICS[metricId]);

  const today = $derived(localDay(scene.now));
  const days = $derived(nextDays(10, scene.now));
  const day = $derived(ui.param && days.includes(ui.param) ? ui.param : today);
  const isToday = $derived(day === today);
  const [start, end] = $derived(dayRange(day));

  // ── Station history for today (one fetch covers every metric) ─────────
  const HISTORY_FIELDS = [
    'air_temperature_c',
    'feels_like_c',
    'rain_accumulation_mm',
    'wind_avg_ms',
    'wind_gust_ms',
    'wind_direction_deg',
    'relative_humidity_pct',
    'dew_point_c',
    'sea_level_pressure_mb',
    'uv_index',
    'solar_radiation_wm2',
  ];
  let history = $state<HistoryRow[]>([]);
  $effect(() => {
    if (!isToday) return;
    const hours = Math.min(48, Math.ceil((scene.now.getTime() - start.getTime()) / 3_600_000) + 1);
    cachedLoad(`hist:${day}:${hours}`, () => api.history(hours, HISTORY_FIELDS), 5 * 60_000)
      .then((h) => (history = h.rows))
      .catch(() => (history = []));
  });

  const dayHours = $derived(
    forecast.hourly
      .map((h) => ({ h, t: parseUtc(h.forecast_time) }))
      .filter((x): x is { h: ForecastHour; t: Date } => x.t != null && x.t >= start && x.t < end),
  );
  const dailyRow = $derived(forecast.daily.find((d) => localDay(forecastDay(d.forecast_time)) === day) ?? null);

  const nowS = $derived(Math.floor(scene.now.getTime() / 1000));
  const range = $derived<[number, number]>([start.getTime() / 1000, end.getTime() / 1000]);

  // ── Series for the chart ──────────────────────────────────────────────
  const BLEND_H = 6;

  /** Linear value at t from sorted [t, v] points (clamped to the ends). */
  function interpolate(pts: [number, number | null][], t: number): number | null {
    const ok = pts.filter((p): p is [number, number] => p[1] != null);
    if (!ok.length) return null;
    if (t <= ok[0]![0]) return ok[0]![1];
    for (let i = 1; i < ok.length; i++) {
      const [t1, v1] = ok[i]!;
      if (t <= t1) {
        const [t0, v0] = ok[i - 1]!;
        return v0 + ((v1 - v0) * (t - t0)) / (t1 - t0);
      }
    }
    return ok.at(-1)![1];
  }

  const chartSeries = $derived.by((): ChartSeries[] =>
    metric.series.map((s) => {
      let past: [number, number | null][] = [];
      if (isToday && s.history) {
        const rows = history.filter((r) => {
          const t = parseUtc(r.window_start);
          return t != null && t >= start;
        });
        if (metric.fromHistory) {
          const [xs, ys] = metric.fromHistory(rows, s.history);
          past = xs.map((x, i) => [x, ys[i] ?? null]);
        } else {
          past = rows.map((r) => [
            Date.parse(`${r.window_start}Z`) / 1000 + 300,
            typeof r[s.history!] === 'number' ? (r[s.history!] as number) : null,
          ]);
        }
        // Station's current reading closes the observed line at "now"
        const cur = live.current?.[s.history];
        if (metric.kind === 'line' && typeof cur === 'number') past.push([nowS, cur]);
      }
      const fut: [number, number | null][] = dayHours
        .map(({ h, t }): [number, number | null] => [
          t.getTime() / 1000 - (metric.kind === 'bars' ? 1800 : 0),
          (h[s.forecast] as number | null) ?? null,
        ])
        .filter(([t]) => !isToday || t >= nowS - (metric.kind === 'bars' ? 1800 : 0));
      // Blend: start the forecast at what the station measures now and fade
      // to the raw forecast over BLEND_H hours, so the curve has no step at
      // "Nu" that doesn't exist in reality (lines only — bars are amounts)
      const cur = s.history ? live.current?.[s.history] : null;
      if (isToday && metric.kind === 'line' && typeof cur === 'number' && fut.length) {
        const f0 = interpolate(fut, nowS);
        if (f0 != null) {
          const delta = cur - f0;
          for (const p of fut) {
            const w = Math.max(0, 1 - (p[0] - nowS) / (BLEND_H * 3600));
            if (p[1] != null && w > 0) p[1] = p[1] + delta * w;
          }
        }
      }
      return { label: s.label, color: s.color, dashed: s.dashed, points: [...past, ...fut] };
    }),
  );

  const arrows = $derived.by(() => {
    if (!metric.arrows) return [];
    const out: { t: number; deg: number }[] = [];
    for (const { h, t } of dayHours) {
      if (t.getHours() % 2 === 0 && h.wind_bearing_deg != null && (!isToday || t.getTime() / 1000 >= nowS))
        out.push({ t: t.getTime() / 1000, deg: h.wind_bearing_deg });
    }
    if (isToday) {
      for (const r of history) {
        const t = parseUtc(r.window_start);
        const d = r.wind_direction_deg;
        if (t && t >= start && t.getMinutes() === 0 && t.getHours() % 2 === 0 && typeof d === 'number')
          out.push({ t: t.getTime() / 1000, deg: d });
      }
    }
    return out;
  });

  // ── Stats for headline / summary ──────────────────────────────────────
  const stats = $derived.by((): DayStats => {
    const primPts = (chartSeries[0]?.points ?? []).filter((p): p is [number, number] => p[1] != null);
    const prim = primPts.map((p) => p[1]);
    const peak = primPts.reduce<[number, number] | null>((a, p) => (!a || p[1] > a[1] ? p : a), null);
    const second = (chartSeries[1]?.points ?? []).map((p) => p[1]).filter((v): v is number => v != null);
    let min = prim.length ? Math.min(...prim) : null;
    let max = prim.length ? Math.max(...prim) : null;
    if (metricId === 'temp' && dailyRow) {
      // the daily forecast may know extremes between forecast hours
      if (dailyRow.temperature_low_c != null) min = Math.min(min ?? Infinity, dailyRow.temperature_low_c);
      if (dailyRow.temperature_high_c != null) max = Math.max(max ?? -Infinity, dailyRow.temperature_high_c);
    }
    const total =
      metric.kind === 'bars' ? prim.reduce((a, b) => a + b, 0) : second.length ? Math.max(...second) : null;
    const noon = dayNoon(day).getTime();
    const ref = isToday ? scene.now.getTime() : noon;
    const hour =
      dayHours.reduce<{ h: ForecastHour; d: number } | null>((best, x) => {
        const d = Math.abs(x.t.getTime() - ref);
        return !best || d < best.d ? { h: x.h, d } : best;
      }, null)?.h ?? null;
    return {
      isToday,
      title: `${weekdayFull(dayNoon(day))} ${dateLong(dayNoon(day))}`,
      now: isToday ? (live.current as CombinedRealtime | null) : null,
      min,
      max,
      maxAt: peak && peak[1] > 0 ? peak[0] : null,
      total,
      hour,
    };
  });

  const head = $derived(metric.headline(stats));
  const cond = $derived(isToday ? scene.condition : (dailyRow?.weather_condition ?? null));

  // "Om temperatur" but "Om UV-indeks" (keep acronyms)
  const aboutTitle = $derived(
    /^[A-ZÆØÅ][A-ZÆØÅ]/.test(metric.label) ? metric.label : metric.label.toLowerCase(),
  );

  let hover = $state<{ t: number; values: (number | null)[] } | null>(null);
</script>

<DayPicker {days} selected={day} {today} onselect={(d) => ui.setParam(d === today ? null : d)} />

<div class="date">{isToday ? 'I dag · ' : ''}{stats.title}</div>

<div class="head">
  <div>
    <div class="big">{hover ? metric.format(hover.values[0] ?? null) : head.big}</div>
    <div class="sub">
      {#if hover}
        kl. {clock(new Date(hover.t * 1000))}{#if hover.values[1] != null && metric.series[1]}
          · {metric.series[1].label.toLowerCase()} {metric.format(hover.values[1])}{/if}
      {:else}
        {head.sub}
      {/if}
    </div>
  </div>
  <div class="cond">
    <WeatherIcon condition={cond} night={isToday && scene.night} size={34} />
    <span>{conditionText(cond)}</span>
  </div>
</div>

<label class="menu">
  <span class="visually-hidden">Måling</span>
  <select bind:value={metricId}>
    {#each METRIC_ORDER as id (id)}
      <option value={id}>{METRICS[id].label}</option>
    {/each}
  </select>
</label>

<div class="chart-card">
  {#key `${metricId}:${day}`}
    <Chart
      series={chartSeries}
      kind={metric.kind}
      {range}
      now={nowS}
      yMin={metric.yMin}
      yMax={metric.yMax}
      minSpan={metric.minSpan}
      format={metric.format}
      {arrows}
      onhover={(h) => (hover = h)}
    />
  {/key}
  {#if chartSeries.every((s) => s.points.length === 0)}
    <div class="nodata">Ingen data for denne dag</div>
  {/if}
</div>

<section class="box">
  <h3>Opsummering</h3>
  <p>{metric.summary(stats)}</p>
</section>

<section class="box">
  <h3>Om {aboutTitle}</h3>
  <p>{metric.about}</p>
</section>

<style>
  .date {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-2);
    margin-bottom: 4px;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }
  .big {
    font-family: var(--font-display);
    font-size: 40px;
    font-weight: 400;
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
  }
  .sub {
    font-size: 14px;
    color: var(--text-2);
    min-height: 1.3em;
  }
  .cond {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    font-size: 12px;
    color: var(--text-2);
    text-align: center;
  }
  .menu select {
    appearance: none;
    font: 600 14px var(--font);
    color: var(--text);
    background: rgb(255 255 255 / 0.12)
      url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")
      no-repeat right 10px center;
    border: 0;
    border-radius: 999px;
    padding: 6px 30px 6px 12px;
    cursor: pointer;
  }
  .menu option {
    color: #111;
  }
  .chart-card {
    position: relative;
    margin: 12px 0 14px;
    padding: 8px 4px 4px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.06);
  }
  .nodata {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: var(--text-2);
    font-size: 14px;
  }
  .box {
    padding: 12px 14px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.06);
    margin-bottom: 10px;
  }
  h3 {
    margin: 0 0 4px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-2);
  }
  p {
    margin: 0;
    font-size: 15px;
    line-height: 1.4;
  }
</style>
