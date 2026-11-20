<!--
  Top section: location, big temperature, condition, today's high/low.

  - Temperature is the station's own reading; condition is the scene's
    (forecast, overridden by what the station observes — see scene.svelte.ts)
  - High/low: the most extreme of the station's observed today, the current
    reading, and the forecast for today
  - As the hero scrolls away, a compact sticky bar ("Gundsømagle  4° | Solrigt")
    fades in, like Apple Weather
  - The browser tab title follows the current temperature
-->
<script lang="ts">
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { temp } from '$lib/format';
  import { SITE, conditionText } from '$lib/i18n/da';
  import { scene } from '$lib/weather/scene.svelte';
  import Icon from './Icon.svelte';

  const c = $derived(live.current);
  const f = $derived(forecast.current);
  const today = $derived(forecast.daily[0]);
  const loading = $derived(live.snapshot == null && forecast.data == null);

  const finite = (...xs: (number | null | undefined)[]) =>
    xs.filter((x): x is number => typeof x === 'number' && Number.isFinite(x));

  const nowTemp = $derived(c?.air_temperature_c ?? f?.temperature_c ?? null);
  const highs = $derived(
    finite(
      live.stats?.air_temp_high_today,
      nowTemp,
      today?.temperature_high_c ?? f?.temperature_high_c,
    ),
  );
  const lows = $derived(
    finite(live.stats?.air_temp_low_today, nowTemp, today?.temperature_low_c ?? f?.temperature_low_c),
  );
  const high = $derived(highs.length ? Math.max(...highs) : null);
  const low = $derived(lows.length ? Math.min(...lows) : null);
  const cond = $derived(conditionText(scene.condition));

  // Scroll progress 0..1 over the first ~140px drives the hero fade-out
  let progress = $state(0);
  const compact = $derived(progress > 0.92);

  $effect(() => {
    const onScroll = () => (progress = Math.min(1, Math.max(0, scrollY / 140)));
    onScroll();
    addEventListener('scroll', onScroll, { passive: true });
    return () => removeEventListener('scroll', onScroll);
  });

  $effect(() => {
    document.title =
      nowTemp == null
        ? SITE.title
        : [temp(nowTemp), cond].filter(Boolean).join(' ') + ` · ${SITE.title}`;
  });
</script>

<div class="bar" class:show={compact} aria-hidden={!compact}>
  <span class="name">{SITE.locationName}</span>
  <span class="sum">{temp(nowTemp)}{cond ? ` | ${cond}` : ''}</span>
</div>

<header class="hero" class:loading style:--p={progress}>
  <div class="loc"><Icon name="location" size={11} /> {SITE.locationSub}</div>
  <h1>{SITE.locationName}</h1>
  <div class="fade">
    <div class="temp" aria-label="Temperatur {temp(nowTemp)}">{temp(nowTemp)}</div>
    <div class="cond">{cond || ' '}</div>
    <div class="hl">
      <span>H:{temp(high)}</span>
      <span>L:{temp(low)}</span>
    </div>
  </div>
</header>

<style>
  .hero {
    position: relative;
    text-align: center;
    padding: 36px 0;
    /* Two-layer shadow keeps white text legible over bright clouds */
    text-shadow:
      0 1px 2px rgb(0 0 0 / 0.18),
      0 0 24px rgb(0 0 0 / 0.14);
  }
  .fade {
    opacity: calc(1 - var(--p) * 1.1);
    transform: translateY(calc(var(--p) * -14px)) scale(calc(1 - var(--p) * 0.06));
    transform-origin: top center;
  }
  .loading .fade {
    animation: pulse 1.4s ease-in-out infinite;
  }
  .loc {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  h1 {
    margin: 2px 0 0;
    font-family: var(--font-display);
    font-size: 34px;
    font-weight: 400;
    letter-spacing: 0.01em;
  }
  .temp {
    font-family: var(--font-display);
    font-size: clamp(88px, 22vw, 108px);
    font-weight: 200;
    line-height: 1;
    padding-left: 0.28em; /* optically centre: the ° hangs right */
  }
  .cond,
  .hl {
    font-size: 20px;
    font-weight: 500;
  }
  .cond {
    margin-top: 2px;
  }
  .hl {
    display: flex;
    justify-content: center;
    gap: 12px;
  }

  /* Compact sticky bar */
  .bar {
    position: fixed;
    inset: 0 0 auto 0;
    z-index: 10;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: calc(env(safe-area-inset-top) + 8px) 12px 14px;
    background: linear-gradient(to bottom, var(--sky-top) 65%, transparent);
    opacity: 0;
    transform: translateY(-8px);
    transition:
      opacity 0.25s,
      transform 0.25s var(--ease);
    pointer-events: none;
    text-shadow: 0 1px 6px rgb(0 0 0 / 0.15);
  }
  .bar.show {
    opacity: 1;
    transform: none;
  }
  .name {
    font-size: 22px;
    font-family: var(--font-display);
  }
  .sum {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-2);
  }

  @keyframes pulse {
    50% {
      opacity: 0.45;
    }
  }
</style>
