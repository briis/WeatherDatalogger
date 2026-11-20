<!--
  Gennemsnit: today's high vs the 1991–2020 normal for this date, as
  "+2° over/under gennemsnitlig dagshøjeste" with both values listed.
  Today's high = the higher of what the station has measured and the
  forecast for the rest of today.
-->
<script lang="ts">
  import { normalHigh } from '$lib/api/climate';
  import { num, temp } from '$lib/format';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  let normal = $state<number | null>(null);
  let failed = $state(false);
  $effect(() => {
    normalHigh(scene.now)
      .then((v) => (normal = v))
      .catch(() => (failed = true));
  });

  const todayHigh = $derived.by(() => {
    const xs = [
      live.stats?.air_temp_high_today,
      live.current?.air_temperature_c,
      forecast.daily[0]?.temperature_high_c,
    ].filter((x): x is number => x != null);
    return xs.length ? Math.max(...xs) : null;
  });

  const diff = $derived(
    todayHigh != null && normal != null ? Math.round(todayHigh) - Math.round(normal) : null,
  );
</script>

{#if diff != null}
  <div class="w-big">{diff > 0 ? '+' : diff < 0 ? '−' : ''}{num(Math.abs(diff), 0)}°</div>
  <div class="lead">
    {diff === 0 ? 'som' : diff > 0 ? 'over' : 'under'} gennemsnitlig dagshøjeste
  </div>
{:else}
  <div class="w-big">–</div>
  <div class="lead w-muted">{failed ? 'Normalen kunne ikke hentes' : 'Henter normal…'}</div>
{/if}
<dl class="w-rows rows">
  <div><dt>I dag</dt><dd>H:{temp(todayHigh)}</dd></div>
  <div><dt>Normal</dt><dd>H:{temp(normal)}</dd></div>
</dl>

<style>
  .lead {
    font-size: 13px;
    font-weight: 600;
    line-height: 1.25;
    margin-top: 2px;
  }
  .rows {
    margin-top: auto;
    font-size: 12px;
  }
  .rows > div {
    padding: 2px 0;
    border: 0;
  }
</style>
