<!--
  The simple "big value + one line of context" widgets, all from the
  station (plus forecast where the station can't measure):
  Føles som, Luftfugtighed, Nedbør, Sigtbarhed, Lyn, Solstråling.
  One component keeps their layout identical; the text logic is per id.
-->
<script lang="ts">
  import { clamp } from '$lib/colors';
  import { parseUtc } from '$lib/api/client';
  import { ago, forecastDay, localDay, mm, num, pct, temp, weekdayFull } from '$lib/format';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def }: { def: WidgetDef } = $props();

  const c = $derived(live.current);
  const f = $derived(forecast.current);

  const view = $derived.by((): { big: string; sub?: string; foot: string; bar?: number } => {
    switch (def.id) {
      case 'feelslike': {
        const fl = c?.feels_like_c ?? f?.feels_like_c ?? null;
        const t = c?.air_temperature_c ?? null;
        const d = fl != null && t != null ? fl - t : 0;
        const humid = (c?.relative_humidity_pct ?? 0) > 60;
        return {
          big: temp(fl),
          foot:
            d <= -1
              ? 'Vinden får det til at føles koldere.'
              : d >= 1
                ? humid
                  ? 'Luftfugtigheden får det til at føles varmere.'
                  : 'Solen får det til at føles varmere.'
                : 'Svarer til den faktiske temperatur.',
        };
      }
      case 'humidity':
        return {
          big: pct(c?.relative_humidity_pct ?? f?.humidity_pct),
          foot: `Dugpunktet er ${temp(c?.dew_point_c ?? f?.dew_point_c)} lige nu.`,
        };
      case 'precipitation': {
        const today = c?.rain_accumulation_mm ?? null;
        const rate = c?.rain_rate_mmh ?? 0;
        const todayKey = localDay(scene.now);
        const next = forecast.daily.find(
          (d) =>
            localDay(forecastDay(d.forecast_time)) > todayKey && (d.precipitation_mm ?? 0) >= 0.5,
        );
        return {
          big: mm(today ?? 0),
          sub: 'I dag',
          foot:
            rate >= 0.2
              ? `Regner nu: ${num(rate, 1)} mm/t.`
              : next
                ? `Næste forventet: ${mm(next.precipitation_mm)} ${weekdayFull(forecastDay(next.forecast_time)).toLowerCase()}.`
                : 'Ingen nedbør forventet de næste dage.',
        };
      }
      case 'visibility': {
        const v = f?.visibility_km ?? null;
        return {
          big: v == null ? '–' : `${num(v, 0)} km`,
          foot:
            v == null
              ? 'Ingen data.'
              : v >= 20
                ? 'Helt klart udsyn.'
                : v >= 10
                  ? 'Godt udsyn.'
                  : v >= 4
                    ? 'Let diset.'
                    : v >= 1
                      ? 'Diset.'
                      : 'Tåge — meget begrænset udsyn.',
        };
      }
      case 'lightning': {
        const n = c?.lightning_count_3h ?? null;
        const last = parseUtc(c?.lightning_last_detected);
        const near = c?.lightning_min_dist_3h_km ?? null;
        return {
          big: num(n ?? 0, 0),
          sub: n === 1 ? 'nedslag på 3 timer' : 'nedslag på 3 timer',
          foot: last
            ? `Seneste lyn ${ago(last, scene.now)}${near != null && (n ?? 0) > 0 ? `, nærmeste ${num(near, 0)} km væk` : ''}.`
            : 'Intet lyn registreret.',
        };
      }
      case 'solar': {
        const w = c?.solar_radiation_wm2 ?? null;
        const lux = c?.illuminance_lux ?? null;
        return {
          big: w == null ? '–' : `${num(w, 0)}`,
          sub: 'W/m²',
          bar: w == null ? undefined : clamp(w / 1000),
          foot: lux != null ? `${num(lux / 1000, lux < 10_000 ? 1 : 0)} klux` : '',
        };
      }
      default:
        return { big: '–', foot: '' };
    }
  });
</script>

<div class="w-big">{view.big}</div>
{#if view.sub}<div class="w-sub">{view.sub}</div>{/if}
{#if view.bar != null}
  <div class="w-track" style:background="linear-gradient(to right, #5e5ce6, #ffd60a 60%, #ff9f0a)">
    <i style:left="{view.bar * 100}%"></i>
  </div>
{/if}
<div class="w-foot">{view.foot}</div>
