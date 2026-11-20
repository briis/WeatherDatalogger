<!--
  Lyn: strikes in the last 3 hours (Tempest's rolling counter), nearest and
  farthest distance, the latest strike, and the 3-hour count over 24 h.
-->
<script lang="ts">
  import { api, parseUtc } from '$lib/api/client';
  import type { HistoryRow } from '$lib/api/types';
  import Chart, { type ChartSeries } from '$lib/components/Chart.svelte';
  import { ago, clock, dateLong, num } from '$lib/format';
  import { cachedLoad, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const c = $derived(live.current);
  const count = $derived(c?.lightning_count_3h ?? 0);
  const last = $derived(parseUtc(c?.lightning_last_detected));

  let rows = $state<HistoryRow[]>([]);
  $effect(() => {
    cachedLoad('hist:lyn:24', () => api.history(24, ['lightning_count_3h']), 5 * 60_000)
      .then((h) => (rows = h.rows))
      .catch(() => (rows = []));
  });
  const nowS = $derived(Math.floor(scene.now.getTime() / 1000));
  const series = $derived<ChartSeries[]>([
    {
      label: 'Nedslag (3 t.)',
      color: '#ffd60a',
      points: rows.map((r) => [Date.parse(`${r.window_start}Z`) / 1000 + 300, Number(r.lightning_count_3h ?? 0)]),
    },
  ]);
  const max24 = $derived(Math.max(0, ...rows.map((r) => Number(r.lightning_count_3h ?? 0))));
</script>

<div class="head">
  <div class="p-big">{num(count, 0)}</div>
  <div class="p-sub">{count === 1 ? 'lynnedslag' : 'lynnedslag'} de seneste 3 timer</div>
</div>

<div class="p-box chart">
  <Chart
    {series}
    range={[nowS - 24 * 3600, nowS]}
    now={nowS}
    yMin={0}
    minSpan={5}
    format={(v) => num(v, 0)}
    height={160}
  />
</div>

<dl class="w-rows p-box rows">
  <div><dt>Nærmeste (3 t.)</dt><dd>{count > 0 ? `${num(c?.lightning_min_dist_3h_km, 0)} km` : '–'}</dd></div>
  <div><dt>Fjerneste (3 t.)</dt><dd>{count > 0 ? `${num(c?.lightning_max_dist_3h_km, 0)} km` : '–'}</dd></div>
  <div>
    <dt>Seneste lyn</dt>
    <dd>{last ? `${dateLong(last)} kl. ${clock(last)} (${ago(last, scene.now)})` : 'Intet registreret'}</dd>
  </div>
  <div><dt>Flest på 3 t. det seneste døgn</dt><dd>{num(max24, 0)}</dd></div>
</dl>

<section class="p-box">
  <h3>Om lyn</h3>
  <p>
    Din Tempest opfanger radiobølgerne fra lynudladninger op til omkring 40 km væk og anslår
    afstanden ud fra signalets styrke — det er et skøn, ikke en præcis position. Elektrisk støj fra
    fx motorer og elektronik kan en sjælden gang give et falsk nedslag. Hører du torden, er du tæt
    nok på til at kunne blive ramt: gå indendørs.
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
