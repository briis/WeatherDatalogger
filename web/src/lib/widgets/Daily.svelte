<!--
  10-dages prognose: one row per day — weekday, icon (with rain chance when
  relevant), low, a temperature bar placed on the shared 10-day range, high.
  Today's bar carries a dot at the current station temperature, and today's
  low/high include what the station has already observed.
-->
<script lang="ts">
  import WeatherIcon from '$lib/components/WeatherIcon.svelte';
  import { clamp, tempColor, tempGradient } from '$lib/colors';
  import { dayLabel, forecastDay, localDay, num, temp } from '$lib/format';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import { ui } from '$lib/stores/ui.svelte';
  import type { WidgetDef } from './registry';

  let { def }: { def: WidgetDef } = $props();

  const DAYS = 10;
  const nowT = $derived(live.current?.air_temperature_c ?? null);

  const rows = $derived.by(() => {
    const today = localDay(scene.now);
    return forecast.daily
      .filter((d) => localDay(forecastDay(d.forecast_time)) >= today)
      .slice(0, DAYS)
      .map((d) => {
        const isToday = localDay(forecastDay(d.forecast_time)) === today;
        let lo = d.temperature_low_c;
        let hi = d.temperature_high_c;
        if (isToday) {
          const obs = [live.stats?.air_temp_low_today, live.stats?.air_temp_high_today, nowT].filter(
            (x): x is number => x != null,
          );
          if (obs.length) {
            lo = Math.min(lo ?? Infinity, ...obs);
            hi = Math.max(hi ?? -Infinity, ...obs);
          }
        }
        return { d, isToday, lo, hi };
      });
  });

  const range = $derived.by(() => {
    const lows = rows.map((r) => r.lo).filter((x): x is number => x != null);
    const highs = rows.map((r) => r.hi).filter((x): x is number => x != null);
    return lows.length && highs.length
      ? { min: Math.min(...lows), max: Math.max(...highs) }
      : { min: 0, max: 10 };
  });

  const pos = (t: number) => clamp((t - range.min) / Math.max(1, range.max - range.min)) * 100;
</script>

{#if rows.length === 0}
  <div class="empty w-muted">Ingen dagsprognose endnu</div>
{:else}
  <ol class="days">
    {#each rows as r (r.d.forecast_time)}
      <li>
        <button
          type="button"
          class="row interactive"
          aria-label="Vis {dayLabel(r.d.forecast_time, scene.now)}"
          onclick={() =>
            ui.open(def.id, r.isToday ? null : localDay(forecastDay(r.d.forecast_time)))}
        >
        <span class="day">{dayLabel(r.d.forecast_time, scene.now)}</span>
        <span class="icon">
          <WeatherIcon condition={r.d.weather_condition} size={26} />
          {#if (r.d.precipitation_probability_pct ?? 0) >= 30}
            <span class="pop">{num(r.d.precipitation_probability_pct, 0)} %</span>
          {/if}
        </span>
        <span class="lo">{temp(r.lo)}</span>
        <span class="bar">
          {#if r.lo != null && r.hi != null}
            <span
              class="fill"
              style:left="{pos(r.lo)}%"
              style:right="{100 - pos(r.hi)}%"
              style:background={tempGradient(r.lo, r.hi)}
            ></span>
            {#if r.isToday && nowT != null}
              <span class="dot" style:left="{pos(nowT)}%" style:background={tempColor(nowT)}></span>
            {/if}
          {/if}
        </span>
        <span class="hi">{temp(r.hi)}</span>
        </button>
      </li>
    {/each}
  </ol>
{/if}

<style>
  .empty {
    margin: auto 0;
    font-size: 14px;
  }
  .days {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    flex: 1;
  }
  li {
    flex: 1;
    display: flex;
    border-top: 1px solid var(--hairline);
  }
  li:first-child {
    border-top: 0;
  }
  .row {
    flex: 1;
    width: 100%;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
    display: grid;
    grid-template-columns: 3.4em 38px 2.4em 1fr 2.4em;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    font-size: 17px;
    font-weight: 500;
  }
  .row:focus-visible {
    outline: 2px solid rgb(255 255 255 / 0.6);
    outline-offset: -2px;
    border-radius: 8px;
  }
  .day {
    font-weight: 600;
  }
  .icon {
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .pop {
    font-size: 11px;
    font-weight: 700;
    color: var(--rain);
    margin-top: -2px;
  }
  .lo {
    color: var(--text-2);
    text-align: right;
  }
  .hi {
    text-align: right;
  }
  .bar {
    position: relative;
    height: 5px;
    border-radius: 3px;
    background: rgb(0 0 0 / 0.18);
  }
  .fill {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 3px;
    min-width: 5px;
  }
  .dot {
    position: absolute;
    top: 50%;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    border: 1.5px solid rgb(30 50 90 / 0.9);
    transform: translate(-50%, -50%);
    box-sizing: content-box;
  }
</style>
