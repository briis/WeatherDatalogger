<!--
  Vind: speed (10-min average when available — Davis' "wind_avg_ms" is
  per-packet instantaneous), gust, direction; compass dial with an arrow
  pointing where the wind blows *to* (Apple style) and speed in the centre.
-->
<script lang="ts">
  import { num } from '$lib/format';
  import { beaufort, compass } from '$lib/i18n/da';
  import { live } from '$lib/stores/weather.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const c = $derived(live.current);
  const s = $derived(live.stats);
  const speed = $derived(s?.wind_speed_avg_10min ?? c?.wind_avg_ms ?? null);
  const dir = $derived(s?.wind_bearing_avg_10min ?? c?.wind_direction_deg ?? null);
  const bf = $derived(beaufort(speed));
</script>

<div class="wrap">
  <dl class="w-rows">
    <div><dt>Vind</dt><dd>{num(speed, speed != null && speed < 10 ? 1 : 0)} m/s</dd></div>
    <div><dt>Vindstød</dt><dd>{num(c?.wind_gust_ms, 1)} m/s</dd></div>
    <div>
      <dt>Retning</dt>
      <dd>{dir != null ? `${num(dir, 0)}° ${compass(dir)}` : '–'}</dd>
    </div>
  </dl>

  <svg class="dial" viewBox="0 0 120 120" role="img" aria-label="Vindretning {compass(dir)}">
    <circle cx="60" cy="60" r="52" fill="none" stroke="rgb(255 255 255 / 0.15)" stroke-width="1" />
    {#each Array.from({ length: 72 }, (_, i) => i * 5) as a (a)}
      <line
        x1="60"
        y1={a % 30 === 0 ? 8 : 10}
        x2="60"
        y2="14"
        stroke="rgb(255 255 255 / {a % 30 === 0 ? 0.7 : 0.3})"
        stroke-width={a % 30 === 0 ? 1.5 : 1}
        transform="rotate({a} 60 60)"
      />
    {/each}
    {#each [['N', 0], ['Ø', 90], ['S', 180], ['V', 270]] as [label, a] (label)}
      <text
        x={60 + 38 * Math.sin((Number(a) * Math.PI) / 180)}
        y={60 - 38 * Math.cos((Number(a) * Math.PI) / 180) + 4}
        text-anchor="middle"
        class="cardinal">{label}</text
      >
    {/each}
    {#if dir != null}
      <!-- From-direction tail (dot) to to-direction head (arrow) -->
      <g transform="rotate({dir} 60 60)">
        <line x1="60" y1="16" x2="60" y2="104" stroke="#fff" stroke-width="2.5" stroke-linecap="round" />
        <circle cx="60" cy="16" r="5" fill="#fff" />
        <path d="M60 112 L53 98 L67 98 Z" fill="#fff" />
      </g>
    {/if}
    <circle cx="60" cy="60" r="20" fill="rgb(40 60 100 / 0.85)" />
    <text x="60" y="61" text-anchor="middle" class="speed">{num(speed, 0)}</text>
    <text x="60" y="73" text-anchor="middle" class="unit">m/s</text>
  </svg>
</div>
{#if bf}
  <div class="bf w-muted">{bf.label} · {bf.force} Beaufort</div>
{/if}

<style>
  .wrap {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 14px;
    align-items: center;
  }
  .dial {
    width: 104px;
    height: 104px;
  }
  .cardinal {
    font-size: 11px;
    font-weight: 600;
    fill: rgb(255 255 255 / 0.85);
  }
  .speed {
    font-size: 17px;
    font-weight: 600;
    fill: #fff;
  }
  .unit {
    font-size: 9px;
    fill: rgb(255 255 255 / 0.75);
  }
  .bf {
    font-size: 12px;
    margin-top: 2px;
  }
</style>
