<!--
  Måne: today's moon large, rise/set, the next four principal phases, and
  a 30-day calendar of drawn phases.
-->
<script lang="ts">
  import SunCalc from 'suncalc';
  import MoonGlyph from '$lib/components/MoonGlyph.svelte';
  import { STATION, moonInfo, nextPhase } from '$lib/astro';
  import { clock, dateLong, localDay, num, weekday } from '$lib/format';
  import { moonPhaseName } from '$lib/i18n/da';
  import { dayNoon, nextDays } from '$lib/time';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const m = $derived(moonInfo(scene.now));
  const times = $derived(SunCalc.getMoonTimes(scene.now, STATION.lat, STATION.lon));
  const distanceKm = $derived(SunCalc.getMoonPosition(scene.now, STATION.lat, STATION.lon).distance);

  const phases = $derived(
    (
      [
        ['Nymåne', 0],
        ['Første kvarter', 0.25],
        ['Fuldmåne', 0.5],
        ['Sidste kvarter', 0.75],
      ] as const
    )
      .map(([name, p]) => ({ name, at: nextPhase(scene.now, p), p }))
      .sort((a, b) => a.at.getTime() - b.at.getTime()),
  );

  const calendar = $derived(
    nextDays(30, scene.now).map((d) => {
      const ill = SunCalc.getMoonIllumination(dayNoon(d));
      return { d, ill: ill.fraction, waxing: ill.phase < 0.5 };
    }),
  );
  const dayNum = (d: string) => Number(d.slice(8, 10));
  const today = $derived(localDay(scene.now));
</script>

<div class="top">
  <MoonGlyph illumination={m.illumination} waxing={m.waxing} size={120} label={moonPhaseName(m.phase)} />
  <div>
    <div class="p-big">{moonPhaseName(m.phase)}</div>
    <div class="p-sub">{num(m.illumination * 100, 0)} % oplyst · {m.waxing ? 'tiltagende' : 'aftagende'}</div>
  </div>
</div>

<dl class="w-rows p-box rows">
  <div><dt>Måneopgang</dt><dd>{times.rise ? clock(times.rise) : times.alwaysUp ? 'Oppe hele døgnet' : 'Ingen i dag'}</dd></div>
  <div><dt>Månenedgang</dt><dd>{times.set ? clock(times.set) : times.alwaysDown ? 'Nede hele døgnet' : 'Ingen i dag'}</dd></div>
  <div><dt>Afstand</dt><dd>{num(distanceKm / 1000, 0)} tusind km</dd></div>
</dl>

<section class="p-box">
  <h3>Kommende faser</h3>
  <div class="phases">
    {#each phases as ph (ph.name)}
      <div class="ph">
        <MoonGlyph illumination={ph.p === 0 ? 0 : ph.p === 0.5 ? 1 : 0.5} waxing={ph.p < 0.5} size={34} />
        <div class="n">{ph.name}</div>
        <div class="d">{weekday(ph.at)} {dateLong(ph.at)}</div>
      </div>
    {/each}
  </div>
</section>

<section class="p-box">
  <h3>De næste 30 dage</h3>
  <div class="cal">
    {#each calendar as c (c.d)}
      <div class="day" class:today={c.d === today}>
        <MoonGlyph illumination={c.ill} waxing={c.waxing} size={28} />
        <span>{dayNum(c.d)}</span>
      </div>
    {/each}
  </div>
</section>

<section class="p-box">
  <h3>Om månen</h3>
  <p>
    Månen går gennem alle faser på 29,5 dage. Den lyse side vender altid mod solen: på den nordlige
    halvkugle tiltager månen fra højre og aftager mod venstre. Måneopgang og -nedgang flytter sig
    omkring 50 minutter senere hver dag, så nogle dage er der ingen opgang eller nedgang.
  </p>
</section>

<style>
  .top {
    display: flex;
    align-items: center;
    gap: 18px;
    margin-bottom: 12px;
  }
  .rows {
    font-size: 15px;
  }
  .phases {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    text-align: center;
  }
  .ph {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
  }
  .ph .n {
    font-size: 12px;
    font-weight: 600;
  }
  .ph .d {
    font-size: 11px;
    color: var(--text-2);
  }
  .cal {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(40px, 1fr));
    gap: 6px;
  }
  .day {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 4px 0;
    border-radius: 8px;
    font-size: 11px;
    color: var(--text-2);
  }
  .day.today {
    background: rgb(255 255 255 / 0.12);
    color: var(--text);
    font-weight: 700;
  }
</style>
