<!--
  Luftkvalitet: EU CAQI from the AirLink / air-quality monitor (whichever
  holds the air_quality role), band name, gradient track, PM values, and a
  comparison with yesterday's worst value.
-->
<script lang="ts">
  import { api } from '$lib/api/client';
  import { CAQI_GRADIENT, clamp } from '$lib/colors';
  import { localDay, num } from '$lib/format';
  import { caqiLevel } from '$lib/i18n/da';
  import { cachedLoad, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const c = $derived(live.current);
  const caqi = $derived(c?.caqi_pm2p5 != null || c?.caqi_pm10 != null
    ? Math.max(c?.caqi_pm2p5 ?? 0, c?.caqi_pm10 ?? 0)
    : null);

  let yesterday = $state<number | null>(null);
  $effect(() => {
    cachedLoad('daily:3', () => api.daily(3), 10 * 60_000)
      .then((d) => {
        const y = new Date(scene.now.getTime() - 86_400_000);
        yesterday = d.rows.find((r) => r.day === localDay(y))?.caqi_pm2p5_max ?? null;
      })
      .catch(() => (yesterday = null));
  });

  const compare = $derived.by(() => {
    if (caqi == null) return 'Ingen data fra luftkvalitetsmåleren.';
    if (yesterday == null) return `PM2,5 ${num(c?.pm_2p5_ugm3, 1)} · PM10 ${num(c?.pm_10_ugm3, 1)} µg/m³`;
    const d = caqi - yesterday;
    if (Math.abs(d) < 5) return 'Luftkvaliteten svarer til i går.';
    return d < 0 ? 'Bedre luftkvalitet end i går.' : 'Dårligere luftkvalitet end i går.';
  });
</script>

<div class="top">
  <div class="w-sub big">{caqiLevel(caqi)}</div>
  <div class="w-muted idx">CAQI {num(caqi, 0)}</div>
</div>
<div class="w-track" style:background={CAQI_GRADIENT}>
  {#if caqi != null}<i style:left="{clamp(caqi / 100) * 100}%"></i>{/if}
</div>
<div class="w-foot">{compare}</div>

<style>
  .top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
  }
  .big {
    font-size: 22px;
  }
  .idx {
    font-size: 13px;
  }
</style>
