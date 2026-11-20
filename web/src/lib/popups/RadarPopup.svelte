<!--
  Nedbørsradar, full size: the DMI frames of the last 2 hours as an
  animation (play/pause, scrubber, step), a colour legend, and the map
  zoomable/pannable. All frames are preloaded so playback doesn't flicker.
-->
<script lang="ts">
  import RadarMap from '$lib/components/RadarMap.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { ago, clock, num } from '$lib/format';
  import { radar } from '$lib/stores/radar.svelte';
  import { scene } from '$lib/weather/scene.svelte';
  import type { WidgetDef } from '$lib/widgets/registry';

  let { def: _def }: { def: WidgetDef } = $props();

  $effect(() => radar.start());

  const FRAME_MS = 600;
  const HOLD_LAST_MS = 1800;

  const frames = $derived(radar.frames);
  let idx = $state(-1); // -1 = follow the newest frame
  let playing = $state(false);
  const current = $derived(frames.length ? (frames[idx < 0 ? frames.length - 1 : idx] ?? null) : null);
  const shownIdx = $derived(idx < 0 ? frames.length - 1 : idx);

  // Preload every frame once
  const preloaded = new Set<string>();
  $effect(() => {
    for (const f of frames) {
      if (preloaded.has(f.url)) continue;
      preloaded.add(f.url);
      const img = new Image();
      img.src = f.url;
    }
  });

  // Playback loop
  $effect(() => {
    if (!playing || frames.length < 2) return;
    let timer: ReturnType<typeof setTimeout>;
    const step = () => {
      const last = frames.length - 1;
      const i = shownIdx >= last ? 0 : shownIdx + 1;
      idx = i;
      timer = setTimeout(step, i === last ? HOLD_LAST_MS : FRAME_MS);
    };
    timer = setTimeout(step, FRAME_MS);
    return () => clearTimeout(timer);
  });

  // Start playing once frames are there (like Apple)
  let autoStarted = false;
  $effect(() => {
    if (!autoStarted && frames.length > 1) {
      autoStarted = true;
      idx = 0;
      playing = true;
    }
  });

  function toggle() {
    playing = !playing;
  }
  function stepBy(d: number) {
    playing = false;
    const n = frames.length;
    if (!n) return;
    idx = (((shownIdx + d) % n) + n) % n;
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === ' ') {
      e.preventDefault();
      toggle();
    } else if (e.key === 'ArrowLeft') stepBy(-1);
    else if (e.key === 'ArrowRight') stepBy(1);
  }

  const isNewest = $derived(shownIdx === frames.length - 1);
  const stale = $derived(
    frames.length > 0 && scene.now.getTime() - frames[frames.length - 1]!.time.getTime() > 45 * 60_000,
  );
  // Ticks every 30 minutes on the timeline
  const ticks = $derived.by(() => {
    if (frames.length < 2) return [];
    const t0 = frames[0]!.time.getTime();
    const t1 = frames[frames.length - 1]!.time.getTime();
    const out: { pos: number; label: string }[] = [];
    const step = 30 * 60_000;
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
      out.push({ pos: ((t - t0) / (t1 - t0)) * 100, label: clock(new Date(t)) });
    }
    return out;
  });
</script>

<svelte:window onkeydown={onKey} />

<div class="wrap">
  <div class="map">
    <RadarMap interactive frame={current} zoom={6.2} />

    <div class="legend" aria-label="Forklaring">
      <div class="lt">Nedbør</div>
      <div class="scale">
        <span class="bar"></span>
        <ul>
          <li>Ekstrem</li>
          <li>Kraftig</li>
          <li>Moderat</li>
          <li>Let</li>
        </ul>
      </div>
    </div>
  </div>

  <div class="controls">
    <button class="play" type="button" onclick={toggle} aria-label={playing ? 'Pause' : 'Afspil'} disabled={frames.length < 2}>
      {#if playing}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="4" width="5" height="16" rx="1.5" /><rect x="14" y="4" width="5" height="16" rx="1.5" /></svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" /></svg>
      {/if}
    </button>

    <div class="info">
      <div class="when">
        {#if current}
          Radar kl. {clock(current.time)}
          <span class="w-muted">· {isNewest ? `seneste (${ago(current.time, scene.now)})` : ago(current.time, scene.now)}</span>
        {:else if radar.error}
          Ingen radardata
        {:else}
          Henter radar…
        {/if}
      </div>
      <div class="timeline">
        <input
          type="range"
          min="0"
          max={Math.max(0, frames.length - 1)}
          value={shownIdx}
          oninput={(e) => {
            playing = false;
            idx = Number((e.currentTarget as HTMLInputElement).value);
          }}
          aria-label="Tidspunkt"
          disabled={frames.length < 2}
        />
        <div class="ticks">
          {#each ticks as t (t.label)}
            <span style:left="{t.pos}%">{t.label}</span>
          {/each}
        </div>
      </div>
    </div>

    <div class="steps">
      <button type="button" onclick={() => stepBy(-1)} aria-label="Forrige billede">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
      </button>
      <button type="button" onclick={() => stepBy(1)} aria-label="Næste billede">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
      </button>
    </div>
  </div>

  <p class="note w-muted">
    {#if stale}<Icon name="clock" size={11} /> Radaren er ikke opdateret i over 45 min. ·{/if}
    DMI's radarkomposit, de seneste {num(frames.length ? (frames.length - 1) * 10 : 0, 0)} min. i 10-minutters trin. Radaren
    dækker Danmark og ca. 120 km ud; den kan se nedbør fra 1–2 km højde, så let støvregn kan mangle.
  </p>
</div>

<style>
  .wrap {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .map {
    position: relative;
    flex: 1;
    min-height: 260px;
    display: flex;
  }
  .legend {
    position: absolute;
    top: 10px;
    left: 10px;
    z-index: 2;
    padding: 8px 10px;
    border-radius: 12px;
    background: rgb(250 250 252 / 0.88);
    color: #111;
    backdrop-filter: blur(8px);
    font-size: 12px;
    box-shadow: 0 2px 10px rgb(0 0 0 / 0.15);
  }
  .lt {
    font-weight: 700;
    margin-bottom: 6px;
  }
  .scale {
    display: flex;
    gap: 8px;
  }
  .bar {
    width: 5px;
    border-radius: 3px;
    background: linear-gradient(to top, #6ebeff 0%, #2882f5 25%, #1ebe5a 45%, #f0e128 62%, #fa9614 74%, #eb321e 86%, #be3cff 100%);
  }
  .scale ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .controls {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.08);
  }
  .play,
  .steps button {
    display: grid;
    place-items: center;
    border: 0;
    border-radius: 50%;
    color: var(--text);
    background: rgb(255 255 255 / 0.15);
    cursor: pointer;
  }
  .play {
    width: 40px;
    height: 40px;
  }
  .steps {
    display: flex;
    gap: 6px;
  }
  .steps button {
    width: 30px;
    height: 30px;
  }
  button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .when {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 4px;
  }
  .timeline {
    position: relative;
    padding-bottom: 14px;
  }
  input[type='range'] {
    width: 100%;
    accent-color: #fff;
    margin: 0;
  }
  .ticks {
    position: absolute;
    left: 8px;
    right: 8px;
    bottom: 0;
    height: 12px;
  }
  .ticks span {
    position: absolute;
    transform: translateX(-50%);
    font-size: 10px;
    color: var(--text-2);
    white-space: nowrap;
  }
  .note {
    margin: 0 4px;
    font-size: 11px;
    line-height: 1.4;
  }
</style>
