<!--
  Volumetric-looking cloud layer (WebGL), à la Apple Weather.

  One full-viewport canvas, drawn by a fragment shader: domain-warped fBm
  noise slowly evolving in time, thresholded by cloud cover and lit from
  above, so the clouds billow and change shape instead of sliding as flat
  sprites. Stars twinkle through the gaps at night, the clouds drift with
  the station's live wind, and lightning (fx.flash, set by WeatherFx) lights
  them from inside.

  Cheap by design: rendered at reduced resolution (clouds are soft, the
  browser upscales) and at most ~30 fps; paused when the tab is hidden; a
  single static frame with prefers-reduced-motion. If WebGL is unavailable
  `active` stays false and WeatherFx draws its 2D sprite clouds instead.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { fx } from '$lib/weather/fx';
  import type { SkyFamily, TimeOfDay } from '$lib/weather/scene.svelte';

  let {
    family,
    tod,
    preview = false,
    active = $bindable(false),
  }: { family: SkyFamily; tod: TimeOfDay; preview?: boolean; active?: boolean } = $props();

  let canvas: HTMLCanvasElement;

  type RGB = [number, number, number];
  interface Look {
    cover: number; // 0 = clear … 1 = overcast
    opacity: number;
    light: RGB; // lit tops
    shadow: RGB; // undersides
    soft: number; // edge softness
    scale: number; // feature size (smaller = bigger clouds)
    stars: number;
  }

  const COVER: Record<SkyFamily, [min: number, max: number]> = {
    clear: [0.04, 0.12],
    partly: [0.3, 0.6],
    cloudy: [0.72, 0.92],
    rain: [0.85, 0.97],
    snow: [0.8, 0.95],
    fog: [0.65, 0.8],
    storm: [0.9, 1],
  };

  // Live cloud cover nudges the amount within the family's range
  const coverPct = $derived(forecast.current?.cloud_cover_pct ?? null);

  function look(fam: SkyFamily, time: TimeOfDay, pct: number | null): Look {
    const [lo, hi] = COVER[fam];
    const cover = pct == null || preview ? (lo + hi) / 2 : lo + (hi - lo) * Math.min(1, Math.max(0, pct / 100));
    const wet = fam === 'rain' || fam === 'storm';
    const night = time === 'night';
    const twilight = time === 'dawn' || time === 'dusk';

    let light: RGB;
    let shadow: RGB;
    if (night) {
      light = wet ? [0.3, 0.31, 0.4] : [0.42, 0.43, 0.6];
      shadow = wet ? [0.1, 0.11, 0.15] : [0.15, 0.16, 0.26];
    } else if (twilight) {
      light = time === 'dawn' ? [0.98, 0.84, 0.76] : [0.96, 0.78, 0.68];
      shadow = wet ? [0.27, 0.27, 0.33] : [0.42, 0.38, 0.5];
    } else if (wet) {
      light = [0.64, 0.67, 0.73];
      shadow = [0.3, 0.33, 0.39];
    } else if (fam === 'cloudy' || fam === 'snow') {
      light = [0.9, 0.91, 0.94];
      shadow = [0.56, 0.6, 0.67];
    } else if (fam === 'fog') {
      light = [0.88, 0.89, 0.91];
      shadow = [0.72, 0.74, 0.77];
    } else {
      light = [1, 1, 1];
      shadow = [0.72, 0.78, 0.87];
    }
    return {
      cover,
      opacity: fam === 'fog' ? 0.55 : night ? 0.92 : 0.88,
      light,
      shadow,
      soft: fam === 'fog' ? 0.3 : fam === 'clear' ? 0.1 : 0.16,
      scale: fam === 'fog' ? 1.1 : fam === 'clear' ? 2.2 : 1.6,
      stars: night ? (wet || fam === 'snow' ? 0.35 : 1) : 0,
    };
  }

  const VERT = `
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

  const FRAG = `
precision highp float;
uniform vec2 u_res;
uniform float u_time;
uniform vec2 u_drift;
uniform float u_cover;
uniform float u_opacity;
uniform vec3 u_light;
uniform vec3 u_shadow;
uniform float u_soft;
uniform float u_scale;
uniform float u_stars;
uniform float u_flash;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
const mat2 M = mat2(1.6, 1.2, -1.2, 1.6);
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 6; i++) { v += a * noise(p); p = M * p; a *= 0.5; }
  return v;
}
float fbm3(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++) { v += a * noise(p); p = M * p; a *= 0.5; }
  return v;
}

void main() {
  vec2 frag = gl_FragCoord.xy;
  float y = frag.y / u_res.y;                 // 0 bottom, 1 top
  vec2 uv = frag / u_res.y;                   // aspect-correct
  // Slight perspective: features flatten and shrink towards the horizon
  vec2 p = vec2(uv.x, uv.y * 1.25) * u_scale * (0.75 + 0.35 * y) + u_drift;
  float t = u_time * 0.025;

  // Gentle domain warp → billowing, slowly morphing shapes (too much warp
  // turns clouds into marble swirls)
  vec2 q = vec2(fbm3(p * 0.6 + vec2(0.0, t)), fbm3(p * 0.6 + vec2(5.2, 1.3) - t));
  vec2 w = p + 0.75 * q + vec2(t * 0.6, 0.0);
  float n = fbm(w);
  float n2 = fbm(w + vec2(0.03, 0.05));      // sample towards the light (up-right)

  // Large-scale patchiness: partly cloudy skies come in groups, not a veil
  float patch = noise(p * 0.35 + 11.0 + t * 0.2) - 0.5;
  float bias = mix(-0.06, 0.06, y) + patch * 0.22 * (1.0 - u_cover);
  float thr = mix(0.74, 0.3, u_cover);
  float d = smoothstep(thr - u_soft * 0.6, thr + u_soft, n + bias);
  float thick = smoothstep(thr, thr + 0.3, n + bias);

  float lit = clamp(0.62 + (n - n2) * 5.5 - thick * 0.38 + y * 0.12, 0.0, 1.0);
  vec3 col = mix(u_shadow, u_light, lit);
  col += u_flash * vec3(0.75, 0.8, 1.0) * (0.25 + thick * 0.9);
  float a = d * u_opacity;

  // Stars in a jittered grid, only where the cloud is thin
  float star = 0.0;
  if (u_stars > 0.0) {
    vec2 g = frag / (u_res.y / 70.0);
    vec2 id = floor(g);
    float h = hash(id);
    if (h > 0.86) {
      vec2 c = vec2(hash(id + 7.1), hash(id + 3.7)) * 0.8 + 0.1;
      float r = length(fract(g) - c);
      float tw = 0.55 + 0.45 * sin(u_time * (0.8 + h * 2.0) + h * 40.0);
      star = smoothstep(0.09, 0.0, r) * tw * (h - 0.86) / 0.14 * 1.4;
      star *= u_stars * smoothstep(0.15, 0.45, y) * (1.0 - smoothstep(0.0, 0.5, d));
    }
  }

  // Premultiplied alpha over the CSS sky gradient
  vec3 rgb = col * a + vec3(1.0) * star * (1.0 - a);
  gl_FragColor = vec4(rgb, a + star * (1.0 - a));
}`;

  // Live wind: speed and direction (blowing *from* deg → clouds move away)
  const windMs = $derived(live.current?.wind_avg_ms ?? 3);
  const windDeg = $derived(live.current?.wind_direction_deg ?? 270);
  let wind = { ms: 3, deg: 270 };
  $effect(() => {
    wind = { ms: windMs, deg: windDeg };
  });

  // Kept across scene changes so the sky doesn't jump when the look changes
  const t0 = performance.now() - Math.random() * 600_000; // a fresh sky per visit
  let dx = Math.random() * 50;
  let dy = Math.random() * 50;

  // GL setup once
  let gl: WebGLRenderingContext | null = null;
  type UName = 'res' | 'time' | 'drift' | 'cover' | 'opacity' | 'light' | 'shadow' | 'soft' | 'scale' | 'stars' | 'flash';
  const U = {} as Record<UName, WebGLUniformLocation | null>;

  function init(): boolean {
    const ctx = canvas.getContext('webgl', { premultipliedAlpha: true, antialias: false, alpha: true });
    if (!ctx) return false;
    const sh = (type: number, src: string) => {
      const s = ctx.createShader(type)!;
      ctx.shaderSource(s, src);
      ctx.compileShader(s);
      if (!ctx.getShaderParameter(s, ctx.COMPILE_STATUS)) {
        console.warn('SkyClouds shader:', ctx.getShaderInfoLog(s));
        return null;
      }
      return s;
    };
    const vs = sh(ctx.VERTEX_SHADER, VERT);
    const fs = sh(ctx.FRAGMENT_SHADER, FRAG);
    if (!vs || !fs) return false;
    const p = ctx.createProgram()!;
    ctx.attachShader(p, vs);
    ctx.attachShader(p, fs);
    ctx.linkProgram(p);
    if (!ctx.getProgramParameter(p, ctx.LINK_STATUS)) return false;
    ctx.useProgram(p);
    const buf = ctx.createBuffer();
    ctx.bindBuffer(ctx.ARRAY_BUFFER, buf);
    ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), ctx.STATIC_DRAW);
    const loc = ctx.getAttribLocation(p, 'a_pos');
    ctx.enableVertexAttribArray(loc);
    ctx.vertexAttribPointer(loc, 2, ctx.FLOAT, false, 0, 0);
    for (const n of ['res', 'time', 'drift', 'cover', 'opacity', 'light', 'shadow', 'soft', 'scale', 'stars', 'flash'] as UName[])
      U[n] = ctx.getUniformLocation(p, 'u_' + n);
    gl = ctx;
    return true;
  }

  $effect(() => {
    if (!gl && !untrack(init)) {
      active = false;
      return;
    }
    active = true;
    const L = look(family, tod, coverPct);
    const g = gl!;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;
    let lastDraw = 0;
    let lastT = performance.now();

    function resize() {
      // Clouds are soft: ~0.4× device pixels is plenty, capped at ~1 MP
      const dpr = Math.min(devicePixelRatio || 1, 2);
      let s = dpr * 0.42;
      const px = innerWidth * innerHeight * s * s;
      if (px > 1_000_000) s *= Math.sqrt(1_000_000 / px);
      canvas.width = Math.max(1, Math.round(innerWidth * s));
      canvas.height = Math.max(1, Math.round(innerHeight * s));
      g.viewport(0, 0, canvas.width, canvas.height);
    }

    function draw(now: number) {
      const dt = Math.min(0.1, (now - lastT) / 1000);
      lastT = now;
      // Drift with the wind: ~3 m/s → slow glide, 12 m/s → brisk
      const rad = (wind.deg * Math.PI) / 180;
      const speed = 0.006 + Math.min(20, wind.ms) * 0.0022;
      dx += -Math.sin(rad) * speed * dt;
      dy += -Math.cos(rad) * speed * dt;
      g.uniform2f(U.res, canvas.width, canvas.height);
      g.uniform1f(U.time, ((now - t0) / 1000) % 100_000);
      g.uniform2f(U.drift, dx, dy);
      g.uniform1f(U.cover, L.cover);
      g.uniform1f(U.opacity, L.opacity);
      g.uniform3fv(U.light, L.light);
      g.uniform3fv(U.shadow, L.shadow);
      g.uniform1f(U.soft, L.soft);
      g.uniform1f(U.scale, L.scale);
      g.uniform1f(U.stars, L.stars);
      g.uniform1f(U.flash, fx.flash);
      g.clearColor(0, 0, 0, 0);
      g.clear(g.COLOR_BUFFER_BIT);
      g.drawArrays(g.TRIANGLES, 0, 3);
    }

    function frame(now: number) {
      raf = requestAnimationFrame(frame);
      // ~30 fps, except during a lightning flash
      if (now - lastDraw < 32 && fx.flash < 0.02) return;
      lastDraw = now;
      draw(now);
    }

    const onResize = () => {
      resize();
      if (reduced) draw(performance.now());
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (document.visibilityState === 'visible' && !reduced) {
        lastT = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };
    const onLost = (e: Event) => {
      e.preventDefault();
      cancelAnimationFrame(raf);
      gl = null;
      active = false;
    };

    resize();
    if (reduced) draw(performance.now());
    else raf = requestAnimationFrame(frame);
    addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibility);
    canvas.addEventListener('webglcontextlost', onLost);

    return () => {
      cancelAnimationFrame(raf);
      removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibility);
      canvas.removeEventListener('webglcontextlost', onLost);
    };
  });
</script>

<canvas bind:this={canvas} class:hidden={!active} aria-hidden="true"></canvas>

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
  .hidden {
    display: none;
  }
</style>
