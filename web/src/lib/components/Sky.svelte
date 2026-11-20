<!--
  Sets the page's sky gradient from the current condition and whether it's
  night at the station. Renders nothing; it only writes CSS variables on
  <body> (app.css fades between them). Phase 2 adds animated layers
  (clouds, rain, stars) on top.
-->
<script lang="ts">
  import type { WeatherCondition } from '$lib/api/types';
  import { isNight } from '$lib/astro';

  let { condition }: { condition: WeatherCondition | null } = $props();

  type Sky = [top: string, bottom: string];
  const DAY: Record<string, Sky> = {
    clear: ['#2c64a8', '#8ab4dd'],
    cloudy: ['#5b6e84', '#a1aebc'],
    rain: ['#3c4c60', '#71808f'],
    snow: ['#6e8098', '#bfcad6'],
    fog: ['#7d8794', '#b8bec6'],
    storm: ['#262e3b', '#545d6b'],
  };
  const NIGHT: Record<string, Sky> = {
    clear: ['#08152c', '#21406c'],
    cloudy: ['#1b2431', '#3a4656'],
    rain: ['#151c27', '#323d4c'],
    snow: ['#28344a', '#566578'],
    fog: ['#262c35', '#4a525d'],
    storm: ['#0e1219', '#2a313c'],
  };

  function family(c: WeatherCondition | null): string {
    switch (c) {
      case 'cloudy':
      case 'partlycloudy':
      case 'windy-variant':
        return c === 'partlycloudy' ? 'clear' : 'cloudy';
      case 'rainy':
      case 'pouring':
      case 'snowy-rainy':
        return 'rain';
      case 'snowy':
      case 'hail':
        return 'snow';
      case 'fog':
        return 'fog';
      case 'lightning':
      case 'lightning-rainy':
        return 'storm';
      default:
        return 'clear';
    }
  }

  let now = $state(new Date());
  $effect(() => {
    const t = setInterval(() => (now = new Date()), 5 * 60_000);
    return () => clearInterval(t);
  });

  $effect(() => {
    const palette = isNight(now) ? NIGHT : DAY;
    const [top, bottom] = palette[family(condition)] ?? palette.clear!;
    document.body.style.setProperty('--sky-top', top);
    document.body.style.setProperty('--sky-bottom', bottom);
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', top);
  });
</script>
