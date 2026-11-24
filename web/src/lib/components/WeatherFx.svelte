<!--
  Animated weather layer behind the page: one fixed full-viewport <canvas>.
  Layers (by scene): sun/twilight glow, stars, drifting clouds, rain, snow,
  fog bands, lightning flashes. Counts scale with viewport area so a phone
  and a 27" screen look equally dense.

  Cheap by design: clouds are pre-rendered sprites, rain is one stroked path
  per frame, the loop stops when the tab is hidden, and with
  prefers-reduced-motion a single static frame is drawn instead.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import type { WeatherCondition } from '$lib/api/types';
  import { live } from '$lib/stores/weather.svelte';
  import type { SkyFamily, TimeOfDay } from '$lib/weather/scene.svelte';
  import { fx } from '$lib/weather/fx';

  let {
    family,
    tod,
    condition,
    glClouds = false,
  }: {
    family: SkyFamily;
    tod: TimeOfDay;
    condition: WeatherCondition | null;
    /** SkyClouds (WebGL) draws clouds and stars — skip the 2D versions */
    glClouds?: boolean;
  } = $props();

  let canvas: HTMLCanvasElement;

  // Wind tilts rain/snow: 0 m/s straight down, ~12 m/s ≈ 30°. Read
  // untracked inside the animation so a new live reading (every few seconds)
  // doesn't tear down and rebuild the whole scene.
  const windMs = $derived(live.current?.wind_avg_ms ?? 2);
  let wind = 2;
  $effect(() => {
    wind = windMs;
  });

  interface Cloud {
    x: number;
    y: number;
    speed: number;
    sprite: HTMLCanvasElement;
  }
  interface Drop {
    x: number;
    y: number;
    len: number;
    speed: number;
  }
  interface Flake {
    x: number;
    y: number;
    r: number;
    speed: number;
    phase: number;
  }
  interface Star {
    x: number;
    y: number;
    r: number;
    phase: number;
    speed: number;
  }

  const rand = (a: number, b: number) => a + Math.random() * (b - a);

  function cloudSprite(w: number, shade: number, alpha: number): HTMLCanvasElement {
    const h = w * 0.55;
    const c = document.createElement('canvas');
    c.width = Math.ceil(w);
    c.height = Math.ceil(h);
    const g = c.getContext('2d')!;
    const puffs = 7 + Math.floor(Math.random() * 5);
    for (let i = 0; i < puffs; i++) {
      const px = rand(w * 0.2, w * 0.8);
      const py = rand(h * 0.4, h * 0.65);
      const r = rand(w * 0.14, w * 0.26);
      const grad = g.createRadialGradient(px, py, 0, px, py, r);
      const v = Math.round(255 * shade);
      grad.addColorStop(0, `rgba(${v},${v},${Math.min(255, v + 8)},${alpha})`);
      grad.addColorStop(1, `rgba(${v},${v},${Math.min(255, v + 8)},0)`);
      g.fillStyle = grad;
      g.beginPath();
      g.arc(px, py, r, 0, Math.PI * 2);
      g.fill();
    }
    return c;
  }

  $effect(() => {
    // Re-run whenever the scene changes
    const fam = family;
    const time = tod;
    const cond = condition;
    const gl = glClouds;
    const ctx = canvas.getContext('2d')!;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

    let W = 0;
    let H = 0;
    let dpr = 1;
    let clouds: Cloud[] = [];
    let drops: Drop[] = [];
    let flakes: Flake[] = [];
    let stars: Star[] = [];
    let raf = 0;
    let last = performance.now();
    let flash = 0;
    let nextFlash = performance.now() + rand(3000, 8000);

    const night = time === 'night';
    const raining = fam === 'rain' || fam === 'storm' || cond === 'snowy-rainy';
    const snowing = fam === 'snow';
    const stormy = fam === 'storm';
    const foggy = fam === 'fog';
    const cloudCount = { clear: 0, partly: 4, cloudy: 9, rain: 10, snow: 8, fog: 2, storm: 11 }[fam];
    const rainDensity = cond === 'pouring' ? 2.6 : stormy ? 2.2 : cond === 'snowy-rainy' ? 0.6 : 1;
    // Daytime clouds are bright and light; night/rain clouds darker and denser
    const shade = night ? 0.55 : raining || stormy ? 0.72 : fam === 'cloudy' ? 0.9 : 1;
    const alpha = fam === 'partly' ? 0.32 : raining || stormy ? 0.5 : 0.36;

    function setup() {
      dpr = Math.min(devicePixelRatio || 1, 2);
      W = innerWidth;
      H = innerHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const area = (W * H) / (1280 * 800);

      stars =
        !gl && night && (fam === 'clear' || fam === 'partly')
          ? Array.from({ length: Math.round(140 * area * (fam === 'partly' ? 0.5 : 1)) }, () => ({
              x: rand(0, W),
              y: rand(0, H * 0.75),
              r: rand(0.4, 1.4),
              phase: rand(0, Math.PI * 2),
              speed: rand(0.4, 1.4),
            }))
          : [];

      clouds = Array.from({ length: gl ? 0 : Math.round(cloudCount * Math.max(0.6, Math.sqrt(area))) }, () => {
        const w = rand(260, 560) * Math.max(0.7, Math.min(1.3, W / 1100));
        return {
          x: rand(-w, W),
          y: rand(-w * 0.35, H * (fam === 'partly' ? 0.3 : 0.5)),
          speed: rand(4, 14) * (wind > 6 ? 2 : 1),
          sprite: cloudSprite(w, shade, alpha),
        };
      });

      drops = raining
        ? Array.from({ length: Math.round(160 * area * rainDensity) }, () => ({
            x: rand(0, W),
            y: rand(-H, H),
            len: rand(10, 22),
            speed: rand(650, 950),
          }))
        : [];

      flakes = snowing
        ? Array.from({ length: Math.round(140 * area) }, () => ({
            x: rand(0, W),
            y: rand(-H, H),
            r: rand(1, 3.2),
            speed: rand(25, 70),
            phase: rand(0, Math.PI * 2),
          }))
        : [];
    }

    function glow() {
      if (time === 'day' && (fam === 'clear' || fam === 'partly')) {
        const g = ctx.createRadialGradient(W * 0.82, -H * 0.05, 0, W * 0.82, -H * 0.05, H * 0.8);
        g.addColorStop(0, 'rgba(255,248,220,0.35)');
        g.addColorStop(0.4, 'rgba(255,240,200,0.08)');
        g.addColorStop(1, 'rgba(255,240,200,0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      } else if ((time === 'dawn' || time === 'dusk') && fam !== 'storm') {
        const g = ctx.createRadialGradient(W * 0.5, H * 1.1, 0, W * 0.5, H * 1.1, H * 0.9);
        g.addColorStop(0, 'rgba(255,170,100,0.35)');
        g.addColorStop(1, 'rgba(255,170,100,0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      }
    }

    function frame(t: number) {
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      ctx.clearRect(0, 0, W, H);
      glow();

      for (const s of stars) {
        const a = 0.45 + 0.45 * Math.sin(s.phase + t * 0.001 * s.speed);
        ctx.fillStyle = `rgba(255,255,255,${a})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      if (foggy) {
        for (let i = 0; i < 4; i++) {
          const y = H * (0.25 + i * 0.2) + Math.sin(t * 0.0002 + i) * 20;
          const g = ctx.createLinearGradient(0, y - 90, 0, y + 90);
          g.addColorStop(0, 'rgba(230,234,240,0)');
          g.addColorStop(0.5, `rgba(230,234,240,${night ? 0.08 : 0.16})`);
          g.addColorStop(1, 'rgba(230,234,240,0)');
          ctx.fillStyle = g;
          ctx.fillRect(0, y - 90, W, 180);
        }
      }

      for (const c of clouds) {
        c.x += c.speed * dt;
        if (c.x > W + 20) c.x = -c.sprite.width;
        ctx.drawImage(c.sprite, c.x, c.y);
      }

      const slant = Math.min(0.55, wind * 0.045);
      if (drops.length) {
        ctx.strokeStyle = night ? 'rgba(190,210,235,0.35)' : 'rgba(225,235,250,0.45)';
        ctx.lineWidth = 1.1;
        ctx.lineCap = 'round';
        ctx.beginPath();
        for (const d of drops) {
          d.y += d.speed * dt;
          d.x += d.speed * slant * dt;
          if (d.y > H) {
            d.y = rand(-60, -10);
            d.x = rand(-W * slant, W);
          }
          ctx.moveTo(d.x, d.y);
          ctx.lineTo(d.x - d.len * slant, d.y - d.len);
        }
        ctx.stroke();
      }

      if (flakes.length) {
        ctx.fillStyle = 'rgba(255,255,255,0.85)';
        ctx.beginPath();
        for (const f of flakes) {
          f.y += f.speed * dt;
          f.x += (Math.sin(f.phase + t * 0.0012) * 18 + f.speed * slant) * dt;
          if (f.y > H + 5) {
            f.y = -5;
            f.x = rand(0, W);
          }
          ctx.moveTo(f.x + f.r, f.y);
          ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
        }
        ctx.fill();
      }

      if (stormy) {
        if (t > nextFlash) {
          flash = 1;
          nextFlash = t + rand(4000, 11000);
        }
        if (flash > 0.01) {
          ctx.fillStyle = `rgba(235,240,255,${flash * (gl ? 0.18 : 0.35)})`;
          ctx.fillRect(0, 0, W, H);
          // flicker: quick double-flash decay
          flash *= flash > 0.5 ? 0.82 : 0.9;
        }
        fx.flash = flash > 0.01 ? flash : 0;
      }

      if (!reduced) raf = requestAnimationFrame(frame);
    }

    function start() {
      cancelAnimationFrame(raf);
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }

    const onResize = () => {
      setup();
      if (reduced) frame(performance.now());
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') cancelAnimationFrame(raf);
      else if (!reduced) start();
    };

    untrack(setup);
    if (reduced) untrack(() => frame(performance.now()));
    else start();
    addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      fx.flash = 0;
      removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  });
</script>

<canvas bind:this={canvas} aria-hidden="true"></canvas>

<style>
  canvas {
    position: fixed;
    inset: 0;
    width: 100vw;
    height: 100vh;
    height: 100lvh;
    z-index: 0;
    pointer-events: none;
  }
</style>
