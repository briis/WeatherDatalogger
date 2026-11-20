<!--
  Solnedgang / Solopgang (title follows the next event): big time, the sun's
  path over the day as a curve with a dot at its current position, and the
  other event underneath.
-->
<script lang="ts">
  import SunCalc from 'suncalc';
  import { STATION, sunInfo } from '$lib/astro';
  import { clock } from '$lib/format';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const today = $derived(sunInfo(scene.now));
  const tomorrow = $derived(sunInfo(new Date(scene.now.getTime() + 86_400_000)));

  // Next event: before sunrise → sunrise; daytime → sunset; after sunset → tomorrow's sunrise
  const next = $derived.by(() => {
    const n = scene.now;
    if (n < today.sunrise) return { kind: 'Solopgang', at: today.sunrise, other: ['Solnedgang', today.sunset] as const };
    if (n < today.sunset) return { kind: 'Solnedgang', at: today.sunset, other: ['Solopgang', today.sunrise] as const };
    return { kind: 'Solopgang', at: tomorrow.sunrise, other: ['Solnedgang', today.sunset] as const };
  });

  // Curve: sun altitude across the local day, sampled every 20 min
  const W = 140;
  const H = 56;
  const curve = $derived.by(() => {
    const d0 = new Date(scene.now);
    d0.setHours(0, 0, 0, 0);
    const pts: [number, number][] = [];
    let maxAlt = 0;
    const alts: number[] = [];
    for (let i = 0; i <= 72; i++) {
      const t = new Date(d0.getTime() + i * 20 * 60_000);
      const a = SunCalc.getPosition(t, STATION.lat, STATION.lon).altitude;
      alts.push(a);
      maxAlt = Math.max(maxAlt, Math.abs(a));
    }
    const yOf = (a: number) => H / 2 - (a / (maxAlt || 1)) * (H / 2 - 4);
    alts.forEach((a, i) => pts.push([(i / 72) * W, yOf(a)]));
    const nowFrac = (scene.now.getTime() - d0.getTime()) / 86_400_000;
    const nowAlt = SunCalc.getPosition(scene.now, STATION.lat, STATION.lon).altitude;
    return {
      d: pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' '),
      sun: [nowFrac * W, yOf(nowAlt)] as const,
      up: nowAlt > 0,
    };
  });
</script>

<div class="w-big">{clock(next.at)}</div>

<svg viewBox="0 0 {W} {H}" class="arc" aria-hidden="true">
  <defs>
    <clipPath id="above"><rect x="0" y="0" width={W} height={H / 2} /></clipPath>
  </defs>
  <path d={curve.d} fill="none" stroke="rgb(255 255 255 / 0.3)" stroke-width="2" />
  <path d={curve.d} fill="none" stroke="rgb(255 255 255 / 0.85)" stroke-width="2" clip-path="url(#above)" />
  <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="rgb(255 255 255 / 0.4)" stroke-width="1" />
  <circle
    cx={curve.sun[0]}
    cy={curve.sun[1]}
    r="5"
    fill={curve.up ? '#fff' : 'rgb(255 255 255 / 0.45)'}
    style:filter={curve.up ? 'drop-shadow(0 0 4px rgb(255 255 255 / 0.9))' : 'none'}
  />
</svg>

<div class="w-foot">{next.other[0]}: {clock(next.other[1])}</div>

<style>
  .arc {
    width: 100%;
    height: auto;
    margin: auto 0 4px;
    overflow: visible;
  }
</style>
