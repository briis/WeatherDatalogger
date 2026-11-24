<!--
  Page background: a sky gradient picked from the scene (condition family ×
  time of day), written as CSS variables on <body> so app.css can fade
  between them, plus two animated layers: SkyClouds (WebGL volumetric clouds and stars)
  and WeatherFx on top (glow, rain, snow, fog, lightning; it also draws
  simple 2D clouds when WebGL isn't available).
-->
<script lang="ts">
  import { scene, type SkyFamily, type TimeOfDay } from '$lib/weather/scene.svelte';
  import WeatherFx from './WeatherFx.svelte';
  import SkyClouds from './SkyClouds.svelte';

  let glClouds = $state(false);

  type Sky = [top: string, bottom: string];

  const SKIES: Record<TimeOfDay, Record<SkyFamily, Sky>> = {
    day: {
      clear: ['#2a62a8', '#8cb7e0'],
      partly: ['#3a6aa4', '#9dbbd9'],
      cloudy: ['#5b6d82', '#a4b1bf'],
      rain: ['#3b4a5d', '#6f7f90'],
      snow: ['#6b7d95', '#c3ced9'],
      fog: ['#7c8692', '#bcc2ca'],
      storm: ['#252d3a', '#566070'],
    },
    dawn: {
      clear: ['#3c5d93', '#f0b27a'],
      partly: ['#4a5f8a', '#d9a582'],
      cloudy: ['#58627a', '#a99a96'],
      rain: ['#3d4659', '#7a7a84'],
      snow: ['#5f6c87', '#c4b8b8'],
      fog: ['#6f7585', '#b9adab'],
      storm: ['#262b38', '#5b5560'],
    },
    dusk: {
      clear: ['#2d3f78', '#e8956a'],
      partly: ['#36446f', '#c98a73'],
      cloudy: ['#4a5068', '#93807f'],
      rain: ['#323a4c', '#6a6670'],
      snow: ['#4f5874', '#ab9fa3'],
      fog: ['#5d6273', '#9e9294'],
      storm: ['#1f2330', '#4c4652'],
    },
    night: {
      clear: ['#07132a', '#1f3d68'],
      partly: ['#0f1b31', '#2b4366'],
      cloudy: ['#1a2230', '#394454'],
      rain: ['#141b26', '#313b4a'],
      snow: ['#263248', '#536276'],
      fog: ['#252b34', '#48505b'],
      storm: ['#0d1118', '#29303b'],
    },
  };

  $effect(() => {
    const [top, bottom] = SKIES[scene.tod][scene.family];
    document.body.style.setProperty('--sky-top', top);
    document.body.style.setProperty('--sky-bottom', bottom);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', top);
  });
</script>

<SkyClouds family={scene.family} tod={scene.tod} preview={scene.preview.sky != null} bind:active={glClouds} />
<WeatherFx family={scene.family} tod={scene.tod} condition={scene.condition} {glClouds} />
