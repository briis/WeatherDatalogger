<!--
  UV-indeks: station's current UV (Tempest), WHO band, gradient track, and
  a one-line outlook from the forecast for the rest of today.
-->
<script lang="ts">
  import { parseUtc } from '$lib/api/client';
  import { UV_GRADIENT, clamp } from '$lib/colors';
  import { clock, localDay, num } from '$lib/format';
  import { uvLevel } from '$lib/i18n/da';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  const uv = $derived(live.current?.uv_index ?? forecast.current?.uv_index ?? null);

  const outlook = $derived.by(() => {
    const now = scene.now;
    const today = localDay(now);
    const rest = forecast.hourly
      .map((h) => ({ h, t: parseUtc(h.forecast_time) }))
      .filter((x) => x.t && x.t > now && localDay(x.t) === today && x.h.uv_index != null);
    if (!rest.length) return 'Lav resten af dagen.';
    const peak = rest.reduce((a, b) => ((b.h.uv_index ?? 0) > (a.h.uv_index ?? 0) ? b : a));
    const peakUv = peak.h.uv_index ?? 0;
    if (peakUv < 3) return 'Lav resten af dagen.';
    return `${uvLevel(peakUv)} omkring kl. ${clock(peak.t)}.`;
  });
</script>

<div class="w-big">{num(uv, 0)}</div>
<div class="w-sub">{uvLevel(uv)}</div>
<div class="w-track" style:background={UV_GRADIENT}>
  {#if uv != null}<i style:left="{clamp(uv / 11) * 100}%"></i>{/if}
</div>
<div class="w-foot">{outlook}</div>
