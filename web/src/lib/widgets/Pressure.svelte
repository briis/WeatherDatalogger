<!--
  Lufttryk: sea-level pressure on a 960–1050 hPa gauge, with the 3-hour
  trend as an arrow inside the gauge and in words underneath.
-->
<script lang="ts">
  import { clamp } from '$lib/colors';
  import { num } from '$lib/format';
  import { PRESSURE_TREND } from '$lib/i18n/da';
  import { live } from '$lib/stores/weather.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const MIN = 960;
  const MAX = 1050;
  const SWEEP = 270; // degrees, gap at the bottom

  const p = $derived(live.current?.sea_level_pressure_mb ?? null);
  const trend = $derived(live.current?.sea_level_pressure_trend ?? live.current?.pressure_trend ?? null);
  const delta = $derived(
    live.current?.sea_level_pressure_trend_mb ?? live.current?.pressure_trend_mb ?? null,
  );
  const angle = $derived(p == null ? null : -SWEEP / 2 + clamp((p - MIN) / (MAX - MIN)) * SWEEP);

  const ticks = Array.from({ length: 46 }, (_, i) => -SWEEP / 2 + (i * SWEEP) / 45);
</script>

<div class="g">
  <svg viewBox="0 0 120 112" role="img" aria-label="Lufttryk {num(p, 0)} hPa">
    {#each ticks as a, i (i)}
      <line
        x1="60"
        y1="8"
        x2="60"
        y2="18"
        stroke="rgb(255 255 255 / 0.32)"
        stroke-width="1.4"
        stroke-linecap="round"
        transform="rotate({a} 60 60)"
      />
    {/each}
    {#if angle != null}
      <line
        x1="60"
        y1="4"
        x2="60"
        y2="22"
        stroke="#fff"
        stroke-width="3"
        stroke-linecap="round"
        transform="rotate({angle} 60 60)"
      />
    {/if}
    {#if trend === 'Rising' || trend === 'Falling'}
      <path
        d={trend === 'Rising' ? 'M60 30 L54 38 H66 Z' : 'M60 38 L54 30 H66 Z'}
        fill="rgb(255 255 255 / 0.85)"
      />
    {:else if trend === 'Steady'}
      <rect x="53" y="33" width="14" height="2.5" rx="1" fill="rgb(255 255 255 / 0.85)" />
    {/if}
    <text x="60" y="64" text-anchor="middle" class="val">{num(p, 0)}</text>
    <text x="60" y="78" text-anchor="middle" class="unit">hPa</text>
    <text x="26" y="106" text-anchor="middle" class="lh">Lavt</text>
    <text x="94" y="106" text-anchor="middle" class="lh">Højt</text>
  </svg>
</div>
<div class="w-foot">
  {#if trend}
    {PRESSURE_TREND[trend] ?? trend}{delta != null ? ` (${delta > 0 ? '+' : ''}${num(delta, 1)} hPa på 3 t.)` : ''}
  {:else}
    &nbsp;
  {/if}
</div>

<style>
  .g {
    flex: 1;
    display: grid;
    place-items: center;
    min-height: 0;
  }
  svg {
    width: 100%;
    max-width: 120px;
    max-height: 100%;
  }
  .val {
    font-size: 22px;
    font-weight: 500;
    fill: #fff;
  }
  .unit {
    font-size: 11px;
    fill: rgb(255 255 255 / 0.75);
  }
  .lh {
    font-size: 10px;
    fill: rgb(255 255 255 / 0.7);
  }
  .w-foot {
    font-size: 12px;
  }
</style>
