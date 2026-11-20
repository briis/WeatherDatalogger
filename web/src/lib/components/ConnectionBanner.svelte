<!--
  Shown under the hero only when something's wrong, in plain Danish:
  - offline:  can't reach the API at all (we may still show the last values)
  - stale:    connected, but the station hasn't reported for > 10 minutes
  - forecast: the forecast couldn't be fetched (station data still fine)
-->
<script lang="ts">
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { ago, clock, parseUtc } from '$lib/format';

  const STALE_MS = 10 * 60_000;

  let now = $state(new Date());
  $effect(() => {
    const t = setInterval(() => (now = new Date()), 15_000);
    return () => clearInterval(t);
  });

  const observed = $derived(parseUtc(live.current?.recorded_at));
  const stale = $derived(observed != null && now.getTime() - observed.getTime() > STALE_MS);

  const message = $derived.by((): { tone: 'bad' | 'warn'; text: string } | null => {
    if (live.status === 'offline') {
      return {
        tone: 'bad',
        text: observed
          ? `Ingen forbindelse til vejrstationen. Viser data fra kl. ${clock(observed)}.`
          : 'Ingen forbindelse til vejrstationen. Prøver igen…',
      };
    }
    if (stale) {
      return {
        tone: 'warn',
        text: `Vejrstationen har ikke rapporteret ${ago(observed, now)} (kl. ${clock(observed)}).`,
      };
    }
    if (forecast.error && !forecast.data) {
      return { tone: 'warn', text: 'Prognosen kunne ikke hentes. Stationsdata er live.' };
    }
    return null;
  });
</script>

{#if message}
  <div class="banner {message.tone}" role="status">
    <span class="dot"></span>
    {message.text}
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: -12px auto 16px;
    width: fit-content;
    max-width: 100%;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
    border-radius: 999px;
    background: rgb(0 0 0 / 0.25);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    animation: in 0.3s var(--ease);
  }
  .dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .bad .dot {
    background: #ff453a;
  }
  .warn .dot {
    background: #ffcc00;
  }
  @keyframes in {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
</style>
