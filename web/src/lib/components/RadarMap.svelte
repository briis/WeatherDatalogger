<!--
  Leaflet map with the DMI radar overlay and a temperature bubble at the
  station. Basemap: CARTO light by day, dark by night (scene.night).

  Used static in the Vindkort/Radar widget (interactive = false) and, in
  phase 4, interactive + animated in its popup via `frame`.
-->
<script lang="ts">
  import L from 'leaflet';
  import 'leaflet/dist/leaflet.css';
  import { STATION } from '$lib/astro';
  import { temp } from '$lib/format';
  import { radar, type RadarFrame } from '$lib/stores/radar.svelte';
  import { live } from '$lib/stores/weather.svelte';
  import { scene } from '$lib/weather/scene.svelte';

  let {
    interactive = false,
    frame = null,
    zoom = 7,
  }: { interactive?: boolean; frame?: RadarFrame | null; zoom?: number } = $props();

  let el: HTMLDivElement;
  let map: L.Map | undefined;
  let tiles: L.TileLayer | undefined;
  let overlay: L.ImageOverlay | undefined;
  let marker: L.Marker | undefined;

  const shown = $derived(frame ?? radar.latest);
  const night = $derived(scene.night);

  const ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a> · Radar: <a href="https://www.dmi.dk/friedata">DMI</a>';

  $effect(() => {
    map = L.map(el, {
      center: [STATION.lat, STATION.lon],
      zoom,
      zoomControl: interactive,
      attributionControl: true,
      dragging: interactive,
      scrollWheelZoom: interactive,
      doubleClickZoom: interactive,
      touchZoom: interactive,
      boxZoom: interactive,
      keyboard: interactive,
      minZoom: 5,
      maxZoom: 11,
    });
    map.attributionControl.setPrefix(false);
    // Card sizes settle after layout; keep Leaflet in sync
    const ro = new ResizeObserver(() => map?.invalidateSize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      map?.remove();
      map = tiles = overlay = marker = undefined;
    };
  });

  // Basemap follows day/night
  $effect(() => {
    if (!map) return;
    const style = night ? 'dark_all' : 'light_all';
    tiles?.remove();
    tiles = L.tileLayer(`https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`, {
      subdomains: 'abcd',
      attribution: ATTRIBUTION,
      maxZoom: 19,
    }).addTo(map);
    tiles.bringToBack();
  });

  // Radar frame
  $effect(() => {
    if (!map || !radar.bounds || !shown) return;
    if (overlay) overlay.setUrl(shown.url);
    else overlay = L.imageOverlay(shown.url, radar.bounds, { opacity: 0.85, interactive: false, className: 'radar-img' }).addTo(map);
  });

  // Station bubble with the current temperature
  $effect(() => {
    if (!map) return;
    const html = `<div class="bubble">${temp(live.current?.air_temperature_c)}</div>`;
    const icon = L.divIcon({ className: 'station-pin', html, iconSize: [36, 36], iconAnchor: [18, 18] });
    if (marker) marker.setIcon(icon);
    else marker = L.marker([STATION.lat, STATION.lon], { icon, interactive: false, keyboard: false }).addTo(map);
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
    background: #d9dee5;
  }
  .map.night {
    background: #1a1d22;
  }
  .map :global(.radar-img) {
    image-rendering: auto;
  }
  .map :global(.station-pin .bubble) {
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
  .map :global(.leaflet-control-attribution) {
    font-size: 9px;
    background: rgb(255 255 255 / 0.6);
    color: #333;
  }
  .map.night :global(.leaflet-control-attribution) {
    background: rgb(0 0 0 / 0.45);
    color: #ccc;
  }
  .map.night :global(.leaflet-control-attribution a) {
    color: #ddd;
  }
</style>
