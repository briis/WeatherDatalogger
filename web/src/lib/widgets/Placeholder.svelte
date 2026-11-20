<!--
  Phase-1 stand-in for a widget body: shows one live value from the data
  layer (proving the API → store → widget path works end to end) until the
  real widget replaces it in phase 3.
-->
<script lang="ts">
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { hpa, km, mm, ms, num, pct, temp, clock } from '$lib/format';
  import { caqiLevel, compass, uvLevel } from '$lib/i18n/da';
  import { moonInfo, sunInfo } from '$lib/astro';
  import type { WidgetDef } from './registry';

  let { def }: { def: WidgetDef } = $props();

  const preview = $derived.by((): string => {
    const c = live.current;
    const s = live.stats;
    const f = forecast.current;
    switch (def.id) {
      case 'airquality':
        return `CAQI ${num(c?.caqi_pm2p5, 0)} · ${caqiLevel(c?.caqi_pm2p5)}`;
      case 'hourly':
        return `${forecast.hourly.length} timer i prognosen`;
      case 'wind':
        return `${ms(c?.wind_avg_ms, 1)} · ${compass(c?.wind_direction_deg)}`;
      case 'daily':
        return `${forecast.daily.length} dage i prognosen`;
      case 'moon':
        return `${num(moonInfo().illumination * 100, 0)} % oplyst`;
      case 'map':
        return 'Vælges senere';
      case 'sun':
        return clock(sunInfo().sunset);
      case 'uv':
        return `${num(c?.uv_index, 0)} · ${uvLevel(c?.uv_index)}`;
      case 'feelslike':
        return temp(c?.feels_like_c);
      case 'averages':
        return `H: ${temp(s?.air_temp_high_today)}`;
      case 'precipitation':
        return mm(c?.rain_accumulation_mm);
      case 'visibility':
        return km(f?.visibility_km);
      case 'humidity':
        return pct(c?.relative_humidity_pct);
      case 'pressure':
        return hpa(c?.sea_level_pressure_mb);
      case 'lightning':
        return `${num(c?.lightning_count_3h, 0)} på 3 t.`;
      case 'solar':
        return `${num(c?.solar_radiation_wm2, 0)} W/m²`;
      default:
        return '';
    }
  });
</script>

<div class="ph">
  <div class="value">{preview}</div>
  <div class="note">Widget kommer i fase {def.phase}</div>
</div>

<style>
  .ph {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }
  .value {
    font-size: 22px;
    font-weight: 500;
  }
  .note {
    font-size: 12px;
    color: var(--text-3);
  }
</style>
