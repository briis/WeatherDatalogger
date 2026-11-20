<!--
  Colour weather icons (original artwork, 32×32 viewBox): sun, moon, clouds,
  rain, snow, sleet, thunder, fog, wind, hail — combined per HA condition,
  with day/night variants for clear and partly cloudy.
-->
<script lang="ts">
  import type { WeatherCondition } from '$lib/api/types';

  let {
    condition,
    night = false,
    size = 28,
  }: { condition: WeatherCondition | null; night?: boolean; size?: number } = $props();

  const SUN = '#ffd60a';
  const MOON = '#e8e8ef';
  const CLOUD = '#f2f4f7';
  const CLOUD_DARK = '#c9ced6';
  const RAIN = '#5ac8fa';
  const BOLT = '#ffd60a';

  const kind = $derived.by(() => {
    switch (condition) {
      case 'sunny':
        return night ? 'moon' : 'sun';
      case 'clear-night':
        return 'moon';
      case 'partlycloudy':
        return night ? 'cloud-moon' : 'cloud-sun';
      case 'cloudy':
      case 'windy-variant':
        return 'cloud';
      case 'rainy':
        return 'rain';
      case 'pouring':
        return 'pour';
      case 'snowy':
        return 'snow';
      case 'snowy-rainy':
        return 'sleet';
      case 'hail':
        return 'hail';
      case 'lightning':
        return 'thunder';
      case 'lightning-rainy':
        return 'thunder-rain';
      case 'fog':
        return 'fog';
      case 'windy':
        return 'wind';
      default:
        return 'cloud';
    }
  });

  // A cloud whose bottom edge sits at y = 24
  const cloudPath = (dx = 0, dy = 0, s = 1) => {
    const t = (x: number, y: number) => `${dx + x * s},${dy + y * s}`;
    return `M${t(9, 24)} H${dx + 23 * s} A${5 * s},${5 * s} 0 0 0 ${t(23.6, 14.04)} A${7 * s},${7 * s} 0 0 0 ${t(10.2, 12.5)} A${5.75 * s},${5.75 * s} 0 0 0 ${t(9, 24)} Z`;
  };
</script>

<svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" class="wi">
  {#if kind === 'sun'}
    <circle cx="16" cy="16" r="6" fill={SUN} />
    <g stroke={SUN} stroke-width="2.2" stroke-linecap="round">
      {#each [0, 45, 90, 135, 180, 225, 270, 315] as a (a)}
        <line x1="16" y1="4.5" x2="16" y2="7.5" transform="rotate({a} 16 16)" />
      {/each}
    </g>
  {:else if kind === 'moon'}
    <path d="M19.5 4.6A11.5 11.5 0 1 0 27.4 20.5 9 9 0 0 1 19.5 4.6Z" fill={MOON} />
  {:else if kind === 'cloud-sun'}
    <circle cx="11.5" cy="11" r="4.5" fill={SUN} />
    <g stroke={SUN} stroke-width="1.8" stroke-linecap="round">
      {#each [180, 225, 270, 315, 0] as a (a)}
        <line x1="11.5" y1="2.5" x2="11.5" y2="4.3" transform="rotate({a} 11.5 11)" />
      {/each}
    </g>
    <path d={cloudPath(2, 2, 0.9)} fill={CLOUD} />
  {:else if kind === 'cloud-moon'}
    <path d="M12.5 2.8A7.2 7.2 0 1 0 18.6 12.6 5.6 5.6 0 0 1 12.5 2.8Z" fill={MOON} />
    <path d={cloudPath(2, 2, 0.9)} fill={CLOUD} />
  {:else if kind === 'fog'}
    <path d={cloudPath(0, -4)} fill={CLOUD_DARK} />
    <g stroke={CLOUD} stroke-width="2" stroke-linecap="round">
      <line x1="6" y1="24" x2="26" y2="24" />
      <line x1="9" y1="28" x2="23" y2="28" />
    </g>
  {:else if kind === 'wind'}
    <g stroke={CLOUD} stroke-width="2.2" stroke-linecap="round" fill="none">
      <path d="M4 12h15a3.5 3.5 0 1 0-3.5-3.5" />
      <path d="M4 17h21a3.5 3.5 0 1 1-3.5 3.5" />
      <path d="M4 22h10" />
    </g>
  {:else}
    <path d={cloudPath(0, kind === 'cloud' ? 0 : -4)} fill={kind === 'cloud' ? CLOUD : CLOUD_DARK} />
    {#if kind === 'rain' || kind === 'pour' || kind === 'thunder-rain'}
      <g stroke={RAIN} stroke-width="2" stroke-linecap="round">
        <line x1="11" y1="24" x2="9.5" y2="28" />
        <line x1="17" y1="24" x2="15.5" y2="28" />
        {#if kind !== 'thunder-rain'}<line x1="23" y1="24" x2="21.5" y2="28" />{/if}
        {#if kind === 'pour'}
          <line x1="14" y1="27" x2="12.5" y2="31" />
          <line x1="20" y1="27" x2="18.5" y2="31" />
        {/if}
      </g>
    {/if}
    {#if kind === 'snow' || kind === 'sleet'}
      <g fill={CLOUD}>
        <circle cx="11" cy="26" r="1.6" />
        <circle cx="21" cy="26" r="1.6" />
        <circle cx="16" cy="29.5" r="1.6" />
      </g>
      {#if kind === 'sleet'}
        <line x1="16" y1="23.5" x2="15" y2="26.5" stroke={RAIN} stroke-width="2" stroke-linecap="round" />
      {/if}
    {/if}
    {#if kind === 'hail'}
      <g fill="none" stroke={CLOUD} stroke-width="1.5">
        <circle cx="11" cy="26.5" r="1.7" />
        <circle cx="17" cy="27.5" r="1.7" />
        <circle cx="23" cy="26.5" r="1.7" />
      </g>
    {/if}
    {#if kind === 'thunder' || kind === 'thunder-rain'}
      <path d="M19 20.5 14.5 26.5h3.2l-1.2 5 5-7h-3.3l1.3-4Z" fill={BOLT} />
    {/if}
  {/if}
</svg>

<style>
  .wi {
    display: block;
    flex: none;
    filter: drop-shadow(0 1px 2px rgb(0 0 0 / 0.15));
  }
</style>
