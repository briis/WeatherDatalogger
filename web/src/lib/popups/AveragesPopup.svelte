<!--
  Gennemsnit: this month's daily highs (station) against the 1991–2020
  normal for each date, plus the month's average deviation.
-->
<script lang="ts">
  import { api } from '$lib/api/client';
  import { NORMAL_PERIOD, normalHighs } from '$lib/api/climate';
  import type { DailySummary } from '$lib/api/types';
  import Chart, { type ChartSeries } from '$lib/components/Chart.svelte';
  import { clock, localDay, num, temp } from '$lib/format';
  import { cachedLoad, forecast, live } from '$lib/stores/weather.svelte';
  import { cphMidnight, dayNoon } from '$lib/time';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const today = $derived(localDay(scene.now));
  const monthKey = $derived(today.slice(0, 7));
  const monthName = $derived(
    new Intl.DateTimeFormat('da-DK', { timeZone: 'Europe/Copenhagen', month: 'long' }).format(scene.now),
  );
  const monthDays = $derived.by(() => {
    const [y, m] = monthKey.split('-').map(Number) as [number, number];
    const n = new Date(Date.UTC(y, m, 0)).getUTCDate();
    return Array.from({ length: n }, (_, i) => `${monthKey}-${String(i + 1).padStart(2, '0')}`);
  });

  let daily = $state<DailySummary[]>([]);
  let normals = $state<(number | null)[]>([]);
  let normalsFailed = $state(false);
  $effect(() => {
    const n = Number(today.slice(8, 10)) + 1;
    cachedLoad(`daily:${n}`, () => api.daily(n), 10 * 60_000)
      .then((d) => (daily = d.rows))
      .catch(() => (daily = []));
    normalHighs(monthDays.map(dayNoon))
      .then((v) => (normals = v))
      .catch(() => (normalsFailed = true));
  });

  // Today's high: the best of station and forecast so far
  const todayHigh = $derived(
    Math.max(
      live.stats?.air_temp_high_today ?? -Infinity,
      live.current?.air_temperature_c ?? -Infinity,
      forecast.daily[0]?.temperature_high_c ?? -Infinity,
    ),
  );

  const observed = $derived(
    monthDays.map((d) => {
      if (d > today) return null;
      if (d === today) return Number.isFinite(todayHigh) ? todayHigh : null;
      return daily.find((r) => r.day === d)?.air_temp_high_c ?? null;
    }),
  );

  const x = $derived(monthDays.map((d) => dayNoon(d).getTime() / 1000));
  const series = $derived<ChartSeries[]>([
    { label: 'Dagens højeste', color: 'temp', points: x.map((t, i) => [t, observed[i] ?? null]) },
    { label: 'Normal', color: 'rgb(255 255 255 / 0.6)', dashed: true, points: x.map((t, i) => [t, normals[i] ?? null]) },
  ]);
  const range = $derived<[number, number]>([
    cphMidnight(monthDays[0]!).getTime() / 1000,
    cphMidnight(monthDays.at(-1)!).getTime() / 1000 + 86400,
  ]);

  const pairs = $derived(
    observed
      .map((o, i) => [o, normals[i]] as const)
      .filter((p): p is readonly [number, number] => p[0] != null && p[1] != null),
  );
  const avgObs = $derived(pairs.length ? pairs.reduce((a, p) => a + p[0], 0) / pairs.length : null);
  const avgNorm = $derived(pairs.length ? pairs.reduce((a, p) => a + p[1], 0) / pairs.length : null);
  const dev = $derived(avgObs != null && avgNorm != null ? avgObs - avgNorm : null);
  const warmer = $derived(pairs.filter((p) => p[0] > p[1] + 0.5).length);

  let hover = $state<{ t: number; values: (number | null)[] } | null>(null);
  const dm = new Intl.DateTimeFormat('da-DK', { timeZone: 'Europe/Copenhagen', day: 'numeric', month: 'long' });
</script>

<div class="head">
  {#if hover}
    <div class="p-big">{temp(hover.values[0])}</div>
    <div class="p-sub">{dm.format(new Date(hover.t * 1000))} · normal {temp(hover.values[1])}</div>
  {:else if dev != null}
    <div class="p-big">{dev >= 0 ? '+' : '−'}{num(Math.abs(dev), 1)}°</div>
    <div class="p-sub">{monthName} indtil nu, i forhold til normalen for dagshøjeste</div>
  {:else}
    <div class="p-big">–</div>
    <div class="p-sub">{normalsFailed ? 'Normalen kunne ikke hentes' : 'Henter…'}</div>
  {/if}
</div>

<div class="p-box chart">
  <Chart
    {series}
    {range}
    now={Math.floor(scene.now.getTime() / 1000)}
    format={(v) => temp(v)}
    axis="days"
    height={200}
    onhover={(h) => (hover = h)}
  />
</div>

<dl class="w-rows p-box rows">
  <div><dt>Gennemsnitlig højeste i {monthName}</dt><dd>{temp(avgObs)}</dd></div>
  <div><dt>Normal for samme dage</dt><dd>{temp(avgNorm)}</dd></div>
  <div><dt>Dage over normalen</dt><dd>{warmer} af {pairs.length}</dd></div>
</dl>

<section class="p-box">
  <h3>Om gennemsnit</h3>
  <p>
    Normalen er gennemsnittet af dagens højeste temperatur for hver dato i perioden
    {NORMAL_PERIOD} (±7 dage udjævnet), fra Open-Meteos historiske data for stationens position.
    Linjen i farver er din stations målte højeste for hver dag i {monthName}; i dag tæller også
    prognosen for resten af dagen med (sidst opdateret kl. {clock(scene.now)}).
  </p>
</section>

<style>
  .head {
    margin-bottom: 8px;
  }
  .chart {
    padding: 8px 4px 4px;
  }
  .rows {
    font-size: 15px;
  }
</style>
