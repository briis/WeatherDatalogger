<!--
  Sol: the sun's altitude over the chosen day (night / twilight / day
  shading), the times that matter, and how much daylight changes per day.
-->
<script lang="ts">
  import SunCalc from 'suncalc';
  import { STATION } from '$lib/astro';
  import { clock, localDay, num } from '$lib/format';
  import { ui } from '$lib/stores/ui.svelte';
  import { cphMidnight, dayNoon, nextDays } from '$lib/time';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';
  import DayPicker from './DayPicker.svelte';

  let { def: _def }: { def: WidgetDef } = $props();

  const today = $derived(localDay(scene.now));
  const days = $derived(nextDays(10, scene.now));
  const day = $derived(ui.param && days.includes(ui.param) ? ui.param : today);
  const isToday = $derived(day === today);

  const t = $derived(SunCalc.getTimes(dayNoon(day), STATION.lat, STATION.lon));
  const yesterday = $derived(SunCalc.getTimes(new Date(dayNoon(day).getTime() - 86_400_000), STATION.lat, STATION.lon));
  const len = (x: { sunrise: Date; sunset: Date }) => (x.sunset.getTime() - x.sunrise.getTime()) / 60_000;
  const daylight = $derived(len(t));
  const diff = $derived(Math.round(daylight - len(yesterday)));
  const noonAlt = $derived(
    (SunCalc.getPosition(t.solarNoon, STATION.lat, STATION.lon).altitude * 180) / Math.PI,
  );
  const hm = (min: number) => `${Math.floor(min / 60)} t. ${Math.round(min % 60)} min.`;

  // Altitude curve over the local day
  const W = 340;
  const H = 150;
  const curve = $derived.by(() => {
    const d0 = cphMidnight(day).getTime();
    const alts: number[] = [];
    for (let i = 0; i <= 144; i++) {
      alts.push(
        (SunCalc.getPosition(new Date(d0 + i * 10 * 60_000), STATION.lat, STATION.lon).altitude * 180) / Math.PI,
      );
    }
    const maxAbs = Math.max(20, ...alts.map(Math.abs));
    const y = (a: number) => H / 2 - (a / maxAbs) * (H / 2 - 10);
    const x = (i: number) => (i / 144) * W;
    const d = alts.map((a, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(a).toFixed(1)}`).join(' ');
    const frac = (dt: Date) => ((dt.getTime() - d0) / 86_400_000) * W;
    const nowAlt = (SunCalc.getPosition(scene.now, STATION.lat, STATION.lon).altitude * 180) / Math.PI;
    return {
      d,
      horizon: y(0),
      civil: y(-6),
      marks: [t.sunrise, t.solarNoon, t.sunset].map(frac),
      sun: isToday ? { x: frac(scene.now), y: y(nowAlt), up: nowAlt > 0 } : null,
    };
  });

  const hourTicks = [0, 6, 12, 18, 24];
</script>

<DayPicker {days} selected={day} {today} onselect={(d) => ui.setParam(d === today ? null : d)} />

<div class="head">
  <div class="p-big">{hm(daylight)}</div>
  <div class="p-sub">
    Dagslys {isToday ? 'i dag' : ''} · {diff === 0 ? 'samme som dagen før' : `${diff > 0 ? '+' : '−'}${Math.abs(diff)} min. i forhold til dagen før`}
  </div>
</div>

<div class="p-box chart">
  <svg viewBox="0 0 {W} {H + 18}" aria-hidden="true">
    <defs>
      <clipPath id="sun-above"><rect x="0" y="0" width={W} height={curve.horizon} /></clipPath>
      <linearGradient id="sun-sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="rgb(255 214 10 / 0.35)" />
        <stop offset="1" stop-color="rgb(255 214 10 / 0)" />
      </linearGradient>
    </defs>
    <!-- twilight band -->
    <rect x="0" y={curve.horizon} width={W} height={curve.civil - curve.horizon} fill="rgb(255 255 255 / 0.05)" />
    <path d="{curve.d} L{W},{curve.horizon} L0,{curve.horizon} Z" fill="url(#sun-sky)" clip-path="url(#sun-above)" />
    <path d={curve.d} fill="none" stroke="rgb(255 255 255 / 0.3)" stroke-width="2" />
    <path d={curve.d} fill="none" stroke="#ffd60a" stroke-width="2.5" clip-path="url(#sun-above)" />
    <line x1="0" x2={W} y1={curve.horizon} y2={curve.horizon} stroke="rgb(255 255 255 / 0.45)" />
    {#each curve.marks as mx, i (i)}
      <line x1={mx} x2={mx} y1="6" y2={H - 4} stroke="rgb(255 255 255 / 0.15)" stroke-dasharray="3 4" />
    {/each}
    {#if curve.sun}
      <circle
        cx={curve.sun.x}
        cy={curve.sun.y}
        r="6"
        fill={curve.sun.up ? '#fff6c2' : 'rgb(255 255 255 / 0.45)'}
        style:filter={curve.sun.up ? 'drop-shadow(0 0 6px #ffd60a)' : 'none'}
      />
    {/if}
    {#each hourTicks as h (h)}
      <text x={(h / 24) * W} y={H + 14} text-anchor={h === 0 ? 'start' : h === 24 ? 'end' : 'middle'} class="tick"
        >{String(h % 24).padStart(2, '0')}</text
      >
    {/each}
  </svg>
</div>

<dl class="w-rows p-box rows">
  <div><dt>Første lys</dt><dd>{clock(t.dawn)}</dd></div>
  <div><dt>Solopgang</dt><dd>{clock(t.sunrise)}</dd></div>
  <div><dt>Solen højest</dt><dd>{clock(t.solarNoon)} · {num(noonAlt, 0)}° over horisonten</dd></div>
  <div><dt>Solnedgang</dt><dd>{clock(t.sunset)}</dd></div>
  <div><dt>Sidste lys</dt><dd>{clock(t.dusk)}</dd></div>
</dl>

<section class="p-box">
  <h3>Om sol</h3>
  <p>
    Første og sidste lys er borgerlig tusmørke: solen står mindre end 6° under horisonten, og
    det er lyst nok til at være ude uden kunstigt lys (det lyse bånd under horisontlinjen). Tiderne
    er beregnet for stationens position og tager højde for lysets brydning i atmosfæren.
  </p>
</section>

<style>
  .head {
    margin-bottom: 10px;
  }
  .chart svg {
    width: 100%;
    height: auto;
    display: block;
  }
  .tick {
    font-size: 10px;
    fill: rgb(255 255 255 / 0.6);
  }
  .rows {
    font-size: 15px;
  }
</style>
