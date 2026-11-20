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

  /**
   * After every (re)loaded style:
   *  - labels in Danish where OSM has a Danish name (København, Danmark),
   *    otherwise the local name; point labels may switch side to avoid
   *    collisions instead of disappearing
   *  - an invisible 44 px symbol at the station, on top, so MapLibre's label
   *    collision keeps place names out from under the temperature bubble
   */
  function prepareStyle(m: MlMap): void {
    for (const layer of m.getStyle().layers) {
      if (layer.type !== 'symbol') continue;
      // Only place-name labels — road refs / house numbers use other fields
      const field = JSON.stringify(m.getLayoutProperty(layer.id, 'text-field') ?? '');
      if (!field.includes('name')) continue;
      m.setLayoutProperty(layer.id, 'text-field', [
        'coalesce',
        ['get', 'name:da'],
        ['get', 'name'],
      ]);
      // Point labels (cities, towns) may move to another side of their dot
      // instead of vanishing when they'd collide — e.g. København next to
      // the station bubble. Line labels (roads, rivers) stay as they are.
      if ((m.getLayoutProperty(layer.id, 'symbol-placement') ?? 'point') === 'point') {
        m.setLayoutProperty(layer.id, 'text-variable-anchor', ['right', 'left', 'top', 'bottom']);
        m.setLayoutProperty(layer.id, 'text-radial-offset', 0.6);
        m.setLayoutProperty(layer.id, 'text-justify', 'auto');
      }
    }
    if (!m.hasImage('station-blocker')) {
      m.addImage('station-blocker', { width: 44, height: 44, data: new Uint8Array(44 * 44 * 4) });
    }
    if (!m.getSource('station')) {
      m.addSource('station', {
        type: 'geojson',
        data: {
          type: 'Feature',
          properties: {},
          geometry: { type: 'Point', coordinates: [STATION.lon, STATION.lat] },
        },
      });
      m.addLayer({
        id: 'station-blocker',
        type: 'symbol',
        source: 'station',
        layout: {
          'icon-image': 'station-blocker',
          'icon-allow-overlap': true,
          'icon-ignore-placement': false,
        },
      });
    }
  }

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
      // Own one-line credit below (the built-in control wraps to two lines
      // in a narrow card and can't be tapped open in the static widget)
      attributionControl: false,
      minZoom: 4,
      maxZoom: 11,
      fadeDuration: 0,
    });
    m.on('style.load', () => {
      prepareStyle(m);
      styleReady++;
    });

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
    // styleReady (not m.isStyleLoaded()): the station GeoJSON source added in
    // prepareStyle() makes isStyleLoaded() false until it has loaded
    const ready = styleReady;
    const m = map;
    const b = radar.bounds;
    const f = shown;
    if (!m || !b || !f || ready === 0) return;
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

<div class="wrap">
  <div class="map" class:night bind:this={el}></div>
  <div class="credit" class:night>
    © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>
    · <a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a>
    · Radar: <a href="https://www.dmi.dk/friedata" target="_blank" rel="noopener">DMI</a>
  </div>
</div>

<style>
  .wrap {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
  }
  .map {
    flex: 1;
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
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: rgb(40 70 120 / 0.92);
    border: 2px solid #fff;
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.35);
    color: #fff;
    font: 600 13px var(--font);
  }
  .credit {
    position: absolute;
    right: 6px;
    bottom: 6px;
    max-width: calc(100% - 12px);
    padding: 1px 6px;
    border-radius: 6px;
    font-size: 9px;
    line-height: 1.5;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: #444;
    background: rgb(255 255 255 / 0.7);
    pointer-events: auto;
  }
  .credit a {
    color: inherit;
  }
  .credit.night {
    color: #ccc;
    background: rgb(0 0 0 / 0.5);
  }
</style>
