<!--
  Timeprognose: the next 24 hours as a horizontally scrollable strip, with
  "Nu" from the station and sunrise/sunset at their exact minute. Three
  views (temperature / precipitation / wind) via the toggles top-right.
-->
<script lang="ts">
  import WeatherIcon from '$lib/components/WeatherIcon.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { clock, hour, num, temp } from '$lib/format';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { ui } from '$lib/stores/ui.svelte';
  import { buildHourly, type HourPoint } from '$lib/weather/forecastItems';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from './registry';

  let { def }: { def: WidgetDef } = $props();

  type Mode = 'temp' | 'rain' | 'wind';
  let mode = $state<Mode>('temp');
  const MODES: { id: Mode; label: string; icon: 'thermometer' | 'drop' | 'wind' }[] = [
    { id: 'temp', label: 'Temperatur', icon: 'thermometer' },
    { id: 'rain', label: 'Nedbør', icon: 'drop' },
    { id: 'wind', label: 'Vind', icon: 'wind' },
  ];

  const items = $derived(
    buildHourly(forecast.hourly, scene.now, live.current, scene.condition, 24),
  );
  const subtitle = $derived(
    { temp: 'Temperatur (°C)', rain: 'Nedbørschance (%) og mængde (mm)', wind: 'Vind (m/s)' }[mode],
  );

  // A click on the strip opens the popup — unless the user was dragging it
  let dragX = 0;
</script>

<div class="tabs interactive" role="tablist" aria-label="Visning">
  {#each MODES as m (m.id)}
    <button
      type="button"
      role="tab"
      aria-selected={mode === m.id}
      aria-label={m.label}
      class:on={mode === m.id}
      onclick={() => (mode = m.id)}
    >
      <Icon name={m.icon} size={14} />
    </button>
  {/each}
</div>

<div class="sub w-muted">{subtitle}</div>

{#if items.length <= 1}
  <div class="empty w-muted">Ingen timeprognose endnu</div>
{:else}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="strip interactive"
    onpointerdown={(e) => (dragX = e.clientX)}
    onclick={(e) => {
      if (Math.abs(e.clientX - dragX) < 6) ui.open(def.id);
    }}
  >
    {#each items as it, i (i)}
      {#if it.kind === 'sunrise' || it.kind === 'sunset'}
        <div class="col">
          <div class="t">{clock(it.time)}</div>
          <div class="ic"><Icon name={it.kind === 'sunrise' ? 'sun' : 'sunset'} size={22} /></div>
          <div class="v small">{it.kind === 'sunrise' ? 'Solopgang' : 'Solnedgang'}</div>
        </div>
      {:else}
        {@const h = it as HourPoint}
        <div class="col" class:now={h.kind === 'now'}>
          <div class="t">{h.kind === 'now' ? 'Nu' : hour(h.time)}</div>
          <div class="ic">
            {#if mode === 'wind'}
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                style:transform="rotate({(h.bearing ?? 0) + 180}deg)"
                aria-hidden="true"
                ><path d="M12 3 18 19 12 15 6 19Z" fill="currentColor" /></svg
              >
            {:else}
              <WeatherIcon condition={h.condition} night={h.night} size={28} />
            {/if}
            {#if mode !== 'wind' && (h.pop ?? 0) >= 20}
              <span class="pop">{num(h.pop, 0)} %</span>
            {/if}
          </div>
          <div class="v">
            {#if mode === 'temp'}
              {temp(h.temp)}
            {:else if mode === 'rain'}
              {num(h.mm ?? 0, (h.mm ?? 0) > 0 && (h.mm ?? 0) < 10 ? 1 : 0)}
            {:else}
              {num(h.wind, 0)}<span class="g">{h.gust != null ? `(${num(h.gust, 0)})` : ''}</span>
            {/if}
          </div>
        </div>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .tabs {
    position: absolute;
    top: -32px;
    right: -4px;
    display: flex;
    gap: 2px;
    padding: 2px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.1);
  }
  .tabs button {
    display: grid;
    place-items: center;
    width: 30px;
    height: 24px;
    border: 0;
    border-radius: 999px;
    background: none;
    color: var(--text-2);
    cursor: pointer;
  }
  .tabs button.on {
    background: rgb(255 255 255 / 0.28);
    color: var(--text);
  }
  .sub {
    font-size: 12px;
    margin: -4px 0 6px;
  }
  .empty {
    margin: auto 0;
    font-size: 14px;
  }
  .strip {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    scrollbar-width: none;
    margin: 0 calc(var(--card-pad) * -1);
    padding: 4px var(--card-pad) 0;
    cursor: pointer;
    overscroll-behavior-x: contain;
    mask-image: linear-gradient(to right, transparent 0, #000 var(--card-pad), #000 calc(100% - var(--card-pad)), transparent);
  }
  .strip::-webkit-scrollbar {
    display: none;
  }
  .col {
    flex: none;
    min-width: 46px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    font-size: 15px;
    font-weight: 500;
  }
  .t {
    font-size: 14px;
    font-weight: 600;
  }
  .now .t {
    font-weight: 700;
  }
  .ic {
    height: 44px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .pop {
    font-size: 11px;
    font-weight: 700;
    color: var(--rain);
    margin-top: 1px;
  }
  .v {
    font-size: 17px;
  }
  .v.small {
    font-size: 12px;
    color: var(--text-2);
  }
  .g {
    font-size: 11px;
    color: var(--text-2);
    margin-left: 1px;
  }
</style>
