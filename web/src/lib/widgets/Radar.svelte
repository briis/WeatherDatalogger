<!--
  Nedbørsradar (tall): the newest DMI radar frame over Zealand with the
  station's temperature bubble, scan time, and "rain right now" from the
  radar at the station. Tap opens the animated map (popup, phase 4).
-->
<script lang="ts">
  import RadarMap from '$lib/components/RadarMap.svelte';
  import { ago, clock, num } from '$lib/format';
  import { radar } from '$lib/stores/radar.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def: _def }: { def: WidgetDef } = $props();

  $effect(() => radar.start());

  const latest = $derived(radar.latest);
  // A frame older than 45 min means the worker or DMI is behind
  const stale = $derived(latest != null && scene.now.getTime() - latest.time.getTime() > 45 * 60_000);
</script>

<div class="wrap">
  <RadarMap />
  <div class="tag" class:stale>
    {#if latest}
      Radar {clock(latest.time)}{#if stale}&nbsp;· {ago(latest.time, scene.now)}{/if}
    {:else if radar.error}
      Ingen radardata
    {:else}
      Henter radar…
    {/if}
  </div>
</div>
<div class="foot w-muted">
  {#if radar.rainNow != null && radar.rainNow >= 0.1}
    Radaren ser {num(radar.rainNow, 1)} mm/t ved stationen.
  {:else if latest}
    Ingen nedbør på radaren ved stationen.
  {:else}
    &nbsp;
  {/if}
</div>

<style>
  .wrap {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .tag {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 500;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: #fff;
    background: rgb(20 30 50 / 0.65);
    backdrop-filter: blur(6px);
  }
  .tag.stale {
    background: rgb(150 90 0 / 0.8);
  }
  .foot {
    font-size: 12px;
    margin-top: 8px;
  }
</style>
