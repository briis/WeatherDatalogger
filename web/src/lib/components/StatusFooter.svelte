<!-- Data freshness + link state, shown at the bottom like Apple's attribution. -->
<script lang="ts">
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { ago, clock, parseUtc } from '$lib/format';

  let now = $state(new Date());
  $effect(() => {
    const t = setInterval(() => (now = new Date()), 30_000);
    return () => clearInterval(t);
  });

  const observed = $derived(parseUtc(live.current?.recorded_at));
  const stale = $derived(observed != null && now.getTime() - observed.getTime() > 10 * 60_000);
  const label = $derived(
    {
      live: 'Live',
      polling: 'Genopretter forbindelse…',
      connecting: 'Forbinder…',
      offline: 'Offline',
    }[live.status],
  );
</script>

<footer>
  <div class="row">
    <span class="dot {live.status}" class:stale></span>
    {label} · Måling {ago(observed, now)}
    {#if observed}({clock(observed)}){/if}
  </div>
  <div class="src">
    Data fra egen vejrstation (WeatherDatalogger) · Prognose fra Open-Meteo
    {#if forecast.error}<span class="err"> · prognose utilgængelig</span>{/if}
  </div>
</footer>

<style>
  footer {
    text-align: center;
    font-size: 12px;
    color: var(--text-2);
    padding: 28px 0 calc(28px + env(safe-area-inset-bottom));
    line-height: 1.6;
  }
  .row {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    color: var(--text);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #8e8e93;
  }
  .dot.live {
    background: #34c759;
  }
  .dot.polling,
  .dot.connecting {
    background: #ffcc00;
  }
  .dot.offline,
  .dot.stale {
    background: #ff453a;
  }
  .err {
    color: #ffb4ad;
  }
</style>
