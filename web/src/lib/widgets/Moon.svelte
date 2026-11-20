<!--
  Måne: phase name, illumination, next moonrise/moonset, days to full moon,
  and a drawn moon whose lit part matches the phase (northern hemisphere:
  waxing = lit on the right).
-->
<script lang="ts">
  import MoonGlyph from '$lib/components/MoonGlyph.svelte';
  import { moonInfo } from '$lib/astro';
  import { clock, num } from '$lib/format';
  import { moonPhaseName } from '$lib/i18n/da';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const m = $derived(moonInfo(scene.now));
  const days = (d: Date) => Math.max(0, Math.round((d.getTime() - scene.now.getTime()) / 86_400_000));
  const fullInDays = $derived(days(m.nextFull));

  // Next of rise/set that's still ahead today (or tomorrow's rise)
  const nextEvent = $derived.by(() => {
    const now = scene.now;
    const cand: ([string, Date] | null)[] = [
      m.rise && m.rise > now ? ['Måneopgang', m.rise] : null,
      m.set && m.set > now ? ['Månenedgang', m.set] : null,
    ];
    const ev = cand.filter((x): x is [string, Date] => x != null);
    ev.sort((a, b) => a[1].getTime() - b[1].getTime());
    if (ev[0]) return ev[0];
    const t = moonInfo(new Date(now.getTime() + 86_400_000));
    return t.rise ? (['Måneopgang', t.rise] as const) : null;
  });

</script>

<div class="wrap">
  <div>
    <div class="phase">{moonPhaseName(m.phase)}</div>
    <dl class="w-rows">
      <div><dt>Belysning</dt><dd>{num(m.illumination * 100, 0)} %</dd></div>
      {#if nextEvent}
        <div><dt>{nextEvent[0]}</dt><dd>{clock(nextEvent[1])}</dd></div>
      {/if}
      <div>
        <dt>Næste fuldmåne</dt>
        <dd>{fullInDays === 0 ? 'I dag' : fullInDays === 1 ? '1 dag' : `${fullInDays} dage`}</dd>
      </div>
    </dl>
  </div>
  <div class="moon">
    <MoonGlyph
      illumination={m.illumination}
      waxing={m.waxing}
      size={96}
      label="{moonPhaseName(m.phase)}, {num(m.illumination * 100, 0)} % oplyst"
    />
  </div>
</div>

<style>
  .wrap {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 14px;
    align-items: center;
  }
  .phase {
    font-size: 15px;
    font-weight: 600;
    margin: -2px 0 2px;
  }
  .moon {
    width: 96px;
    height: 96px;
  }
</style>
