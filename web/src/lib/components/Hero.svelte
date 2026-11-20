<!--
  Top section: location, big temperature, condition, today's high/low.
  Temperature is the station's own reading; condition comes from the
  forecast (the station can't observe "partly cloudy"). High/low prefers the
  station's observed extremes and falls back to the forecast.
-->
<script lang="ts">
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { temp } from '$lib/format';
  import { SITE, conditionText } from '$lib/i18n/da';
  import Icon from './Icon.svelte';

  const c = $derived(live.current);
  const f = $derived(forecast.current);
  const today = $derived(forecast.daily[0]);

  const high = $derived(
    Math.max(
      live.stats?.air_temp_high_today ?? -Infinity,
      c?.air_temperature_c ?? -Infinity,
      today?.temperature_high_c ?? f?.temperature_high_c ?? -Infinity,
    ),
  );
  const low = $derived(
    Math.min(
      live.stats?.air_temp_low_today ?? Infinity,
      c?.air_temperature_c ?? Infinity,
      today?.temperature_low_c ?? f?.temperature_low_c ?? Infinity,
    ),
  );
</script>

<header class="hero">
  <div class="loc"><Icon name="location" size={11} /> {SITE.locationSub}</div>
  <h1>{SITE.locationName}</h1>
  <div class="temp">{temp(c?.air_temperature_c ?? f?.temperature_c)}</div>
  <div class="cond">{conditionText(f?.weather_condition)}</div>
  <div class="hl">
    H:{temp(Number.isFinite(high) ? high : null)}&nbsp;&nbsp;L:{temp(
      Number.isFinite(low) ? low : null,
    )}
  </div>
</header>

<style>
  .hero {
    text-align: center;
    padding: 28px 0 32px;
    text-shadow: 0 1px 8px rgb(0 0 0 / 0.12);
  }
  .loc {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  h1 {
    margin: 2px 0 0;
    font-family: var(--font-display);
    font-size: 32px;
    font-weight: 400;
  }
  .temp {
    font-family: var(--font-display);
    font-size: 96px;
    font-weight: 200;
    line-height: 1;
    padding-left: 0.3em; /* optically centre: the ° hangs right */
  }
  .cond {
    font-size: 20px;
    font-weight: 500;
    margin-top: 4px;
  }
  .hl {
    font-size: 20px;
    font-weight: 500;
  }
</style>
