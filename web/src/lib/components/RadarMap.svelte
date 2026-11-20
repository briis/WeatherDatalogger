<!--
  MapLibre map with the DMI radar overlay and a temperature bubble at the
  station. Basemap: OpenFreeMap vector tiles (no API key, no limits) —
  Positron by day, Dark by night (scene.night).

  Used static in the Nedbørsradar widget (interactive = false) and, in
  phase 4, interactive + animated in its popup via `frame`.
-->
<script lang="ts">
  import { Map as MlMap, Marker, setWorkerUrl, type ImageSource } from 'maplibre-gl';
  import 'maplibre-gl/dist/maplibre-gl.css';
  // MapLibre 6 resolves its worker relative to its own module, which breaks
  // once Vite has bundled it — hand it a Vite-built worker URL instead.
  import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

  setWorkerUrl(workerUrl);
  import { untrack } from 'svelte';
  import { STATION } from '$lib/astro';
  import { temp } from '$lib/format';
  import { radar, type RadarFrame } from '$lib/stores/radar.svelte';
  import { live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';

  let {
    interactive = false,
    frame = null,
    zoom = 5.7,
  }: { interactive?: boolean; frame?: RadarFrame | null; zoom?: number } = $props();

  const STYLE = {
    day: 'https://tiles.openfreemap.org/styles/positron',
    night: 'https://tiles.openfreemap.org/styles/dark',
  };
  const SOURCE = 'dmi-radar';

  let el: HTMLDivElement;
  let map = $state<MlMap | null>(null);
  let styleReady = $state(0); // bumps on every (re)loaded style
  let bubble: HTMLDivElement | undefined;

  const shown = $derived(frame ?? radar.latest);
  const night = $derived(scene.night);

  /** [[S, W], [N, E]] → MapLibre corner order TL, TR, BR, BL as [lon, lat]. */
  function corners(b: [[number, number], [number, number]]) {
    const [[s, w], [n, e]] = b;
    return [
      [w, n],
      [e, n],
      [e, s],
      [w, s],
    ] as [[number, number], [number, number], [number, number], [number, number]];
  }

  $effect(() => {
    const m = new MlMap({
      container: el,
      style: untrack(() => (night ? STYLE.night : STYLE.day)),
      center: [STATION.lon, STATION.lat],
      zoom,
      interactive,
      // Static widget: show the attribution in full (it can't be tapped open)
      attributionControl: {
        compact: interactive,
        customAttribution: 'Radar: <a href="https://www.dmi.dk/friedata" target="_blank" rel="noopener">DMI</a>',
      },
      minZoom: 4,
      maxZoom: 11,
      fadeDuration: 0,
    });
    m.on('style.load', () => styleReady++);

    bubble = document.createElement('div');
    bubble.className = 'bubble';
    new Marker({ element: bubble }).setLngLat([STATION.lon, STATION.lat]).addTo(m);

    map = m;
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      m.remove();
      map = null;
    };
  });

  // Basemap follows day/night; the radar layer is re-added on style.load
  let currentStyle = '';
  $effect(() => {
    const url = night ? STYLE.night : STYLE.day;
    if (!map) return;
    if (currentStyle && currentStyle !== url) map.setStyle(url);
    currentStyle = url;
  });

  // Radar overlay — (re)created after each style load, otherwise just swapped
  $effect(() => {
    void styleReady;
    const m = map;
    const b = radar.bounds;
    const f = shown;
    if (!m || !b || !f || !m.isStyleLoaded()) return;
    const src = m.getSource(SOURCE) as ImageSource | undefined;
    if (src) {
      src.updateImage({ url: f.url, coordinates: corners(b) });
      return;
    }
    m.addSource(SOURCE, { type: 'image', url: f.url, coordinates: corners(b) });
    // Put radar under the first label layer so place names stay readable
    const firstLabel = m.getStyle().layers.find((l) => l.type === 'symbol')?.id;
    m.addLayer(
      {
        id: SOURCE,
        type: 'raster',
        source: SOURCE,
        paint: { 'raster-opacity': 0.85, 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
      },
      firstLabel,
    );
  });

  // Station bubble with the current temperature
  $effect(() => {
    const t = temp(live.current?.air_temperature_c);
    if (bubble) bubble.textContent = t;
  });
</script>

<div class="map" class:night bind:this={el}></div>

<style>
  .map {
    width: 100%;
    height: 100%;
    min-height: 180px;
    border-radius: 12px;
    overflow: hidden;
    background: #e8eaed;
  }
  .map.night {
    background: #1b1d21;
  }
  .map :global(.bubble) {
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: rgb(40 70 120 / 0.92);
    border: 2px solid #fff;
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.35);
    color: #fff;
    font: 600 13px var(--font);
  }
  .map :global(.maplibregl-ctrl-attrib) {
    font-size: 10px;
  }
  .map.night :global(.maplibregl-ctrl-attrib) {
    background: rgb(0 0 0 / 0.5);
    color: #ccc;
  }
  .map.night :global(.maplibregl-ctrl-attrib a) {
    color: #ddd;
  }
</style>
