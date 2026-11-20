<!--
  Luftkvalitet: current EU CAQI band, the pollutants behind it, the last
  24 h from history, and what each band means for health.
-->
<script lang="ts">
  import { api } from '$lib/api/client';
  import type { HistoryRow } from '$lib/api/types';
  import Chart, { type ChartSeries } from '$lib/components/Chart.svelte';
  import { CAQI_GRADIENT, clamp } from '$lib/colors';
  import { clock, num } from '$lib/format';
  import { caqiLevel } from '$lib/i18n/da';
  import { cachedLoad, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const c = $derived(live.current);
  const caqi = $derived(
    c?.caqi_pm2p5 != null || c?.caqi_pm10 != null ? Math.max(c?.caqi_pm2p5 ?? 0, c?.caqi_pm10 ?? 0) : null,
  );

  const BANDS = [
    { max: 25, name: 'Meget god', color: '#79bc6a', advice: 'Ingen risiko. Godt vejr til at lufte ud og være udenfor.' },
    { max: 50, name: 'God', color: '#bbcf4c', advice: 'Ingen gener for de fleste.' },
    { max: 75, name: 'Middel', color: '#eec20b', advice: 'Følsomme personer (astma, hjerte-/lungesygdom) kan mærke det ved længere tids anstrengelse udenfor.' },
    { max: 100, name: 'Dårlig', color: '#f29305', advice: 'Følsomme personer bør skære ned på anstrengelse udenfor; andre kan få irriterede øjne og luftveje.' },
    { max: Infinity, name: 'Meget dårlig', color: '#e8416f', advice: 'Alle bør begrænse længere tids anstrengelse udenfor. Hold vinduer lukket.' },
  ];
  const band = $derived(caqi == null ? null : (BANDS.find((b) => caqi < b.max) ?? BANDS[4]!));

  let rows = $state<HistoryRow[]>([]);
  $effect(() => {
    cachedLoad('hist:aq:24', () => api.history(24, ['caqi_pm2p5', 'caqi_pm10', 'pm_2p5_ugm3']), 5 * 60_000)
      .then((h) => (rows = h.rows))
      .catch(() => (rows = []));
  });
  const nowS = $derived(Math.floor(scene.now.getTime() / 1000));
  const series = $derived<ChartSeries[]>([
    {
      label: 'CAQI',
      color: '#bbcf4c',
      points: rows.map((r) => [
        Date.parse(`${r.window_start}Z`) / 1000 + 300,
        Math.max(Number(r.caqi_pm2p5 ?? 0), Number(r.caqi_pm10 ?? 0)) || null,
      ]),
    },
  ]);
  let hover = $state<{ t: number; values: (number | null)[] } | null>(null);
</script>

<div class="head">
  <div class="p-big">{hover ? `CAQI ${num(hover.values[0], 0)}` : (band?.name ?? '–')}</div>
  <div class="p-sub">
    {hover ? `kl. ${clock(new Date(hover.t * 1000))} · ${caqiLevel(hover.values[0])}` : `CAQI ${num(caqi, 0)} (EU-indeks)`}
  </div>
</div>
<div class="w-track" style:background={CAQI_GRADIENT}>
  {#if caqi != null}<i style:left="{clamp(caqi / 100) * 100}%"></i>{/if}
</div>

<div class="p-box chart">
  <Chart
    {series}
    range={[nowS - 24 * 3600, nowS]}
    now={nowS}
    yMin={0}
    minSpan={50}
    format={(v) => num(v, 0)}
    height={170}
    onhover={(h) => (hover = h)}
  />
</div>

<dl class="w-rows p-box rows">
  <div><dt>PM2,5 (fine partikler)</dt><dd>{num(c?.pm_2p5_ugm3, 1)} µg/m³</dd></div>
  <div><dt>PM10 (grove partikler)</dt><dd>{num(c?.pm_10_ugm3, 1)} µg/m³</dd></div>
  {#if c?.pm_1_ugm3 != null}<div><dt>PM1</dt><dd>{num(c.pm_1_ugm3, 1)} µg/m³</dd></div>{/if}
  {#if c?.pm_2p5_24h_ugm3 != null}<div><dt>PM2,5 gennemsnit 24 t.</dt><dd>{num(c.pm_2p5_24h_ugm3, 1)} µg/m³</dd></div>{/if}
  {#if c?.aqi_pm2p5 != null}<div><dt>US AQI (PM2,5)</dt><dd>{num(c.aqi_pm2p5, 0)}</dd></div>{/if}
</dl>

{#if band}
  <section class="p-box">
    <h3>Sundhed</h3>
    <p>{band.advice}</p>
  </section>
{/if}

<section class="p-box">
  <h3>Skalaen</h3>
  <ul class="bands">
    {#each BANDS as b, i (b.name)}
      <li class:on={b === band}>
        <span class="sw" style:background={b.color}></span>
        <span class="bn">{b.name}</span>
        <span class="br">{i === 0 ? '0' : BANDS[i - 1]!.max}{b.max === Infinity ? '+' : `–${b.max}`}</span>
      </li>
    {/each}
  </ul>
</section>

<section class="p-box">
  <h3>Om luftkvalitet</h3>
  <p>
    CAQI (Common Air Quality Index) er det fælleseuropæiske indeks. Her beregnes det ud fra
    partikler (PM2,5 og PM10) målt af din luftkvalitetsmåler, og det værste af de to tæller. Partikler
    kommer især fra brændeovne, trafik og landbrug, og om vinteren er værdierne ofte højest om
    aftenen i stille vejr.
  </p>
</section>

<style>
  .head {
    margin-bottom: 4px;
  }
  .chart {
    margin-top: 12px;
    padding: 8px 4px 4px;
  }
  .rows {
    font-size: 15px;
  }
  .bands {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
    font-size: 14px;
  }
  .bands li {
    display: grid;
    grid-template-columns: 14px 1fr auto;
    gap: 10px;
    align-items: center;
    padding: 4px 6px;
    border-radius: 8px;
  }
  .bands li.on {
    background: rgb(255 255 255 / 0.1);
    font-weight: 600;
  }
  .sw {
    width: 14px;
    height: 14px;
    border-radius: 4px;
  }
  .br {
    color: var(--text-2);
  }
</style>
