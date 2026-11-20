<!--
  Måne: phase name, illumination, next moonrise/moonset, days to full moon,
  and a drawn moon whose lit part matches the phase (northern hemisphere:
  waxing = lit on the right).
-->
<script lang="ts">
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

  // Terminator: an ellipse whose x-radius goes R → 0 → R as illumination 0 → 0.5 → 1
  const R = 40;
  const moonPath = $derived.by(() => {
    const f = m.illumination;
    const rx = Math.abs(1 - 2 * f) * R;
    const litRight = m.waxing;
    const outerSweep = litRight ? 1 : 0;
    // Lit limb on one side, terminator ellipse back; bulges outward past half
    const innerSweep = f > 0.5 ? (litRight ? 1 : 0) : litRight ? 0 : 1;
    return `M50 ${50 - R} A${R} ${R} 0 0 ${outerSweep} 50 ${50 + R} A${rx} ${R} 0 0 ${innerSweep} 50 ${50 - R} Z`;
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
  <svg viewBox="0 0 100 100" class="moon" role="img" aria-label="{moonPhaseName(m.phase)}, {num(m.illumination * 100, 0)} % oplyst">
    <defs>
      <radialGradient id="moonlit" cx="45%" cy="40%" r="65%">
        <stop offset="0%" stop-color="#f4f4f6" />
        <stop offset="100%" stop-color="#b9bcc4" />
      </radialGradient>
    </defs>
    <circle cx="50" cy="50" r={R} fill="rgb(0 0 0 / 0.35)" />
    <path d={moonPath} fill="url(#moonlit)" />
    <!-- a few maria for texture -->
    <g fill="rgb(120 124 135 / 0.28)" clip-path="url(#moonclip)">
      <circle cx="40" cy="38" r="7" /><circle cx="58" cy="46" r="9" /><circle cx="46" cy="62" r="5" />
    </g>
    <clipPath id="moonclip"><path d={moonPath} /></clipPath>
  </svg>
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
