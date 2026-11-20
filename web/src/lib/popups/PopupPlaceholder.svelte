<!-- Phase-1 stand-in for a popup body (real popups land in phase 4). -->
<script lang="ts">
  import { api } from '$lib/api/client';
  import { cachedLoad } from '$lib/stores/weather.svelte';
  import { clock, parseUtc, temp } from '$lib/format';
  import type { WidgetDef } from '$lib/widgets/registry';

  let { def }: { def: WidgetDef } = $props();

  // Proves the history endpoint works from inside a popup
  const history = cachedLoad('history:24:temp', () => api.history(24, ['air_temperature_c']));
</script>

<p>Popup for <strong>{def.title}</strong> bygges i fase 4 — med dag-vælger, graf og forklaring.</p>

{#await history}
  <p class="muted">Henter historik…</p>
{:then h}
  {@const last = h.rows.at(-1)}
  <p class="muted">
    {h.rows.length} målinger det seneste døgn{#if last}; seneste
      {clock(parseUtc(last.window_start))}: {temp(last.air_temperature_c as number | null)}{/if}
  </p>
{:catch e}
  <p class="muted">Kunne ikke hente historik: {e.message}</p>
{/await}

<style>
  .muted {
    color: var(--text-2);
    font-size: 14px;
  }
</style>
