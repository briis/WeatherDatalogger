<!--
  Day chart (uPlot) for the Vejrforhold popup.

  Each input series is split at "now" into an observed part (dimmed, like
  Apple) and a forecast part. color = 'temp' paints the line with the
  temperature colour scale along the y-axis. kind = 'bars' draws hourly bars.
  A vertical "Nu" line marks the present; hovering/dragging reports the
  value under the cursor through `onhover`.
-->
<script lang="ts" module>
  export interface ChartSeries {
    label: string;
    color: string; // CSS colour, or 'temp' / 'uv' for a value-coloured line
    dashed?: boolean;
    /** [unix seconds, value] pairs, sorted */
    points: [number, number | null][];
  }
</script>

<script lang="ts">
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { tempColor, uvColor } from '$lib/colors';

  let {
    series,
    kind = 'line',
    range,
    now,
    yMin,
    yMax,
    minSpan = 2,
    format,
    arrows = [],
    axis = 'hours',
    height = 220,
    onhover,
  }: {
    series: ChartSeries[];
    kind?: 'line' | 'bars';
    range: [number, number];
    now: number;
    yMin?: number;
    yMax?: number;
    /** smallest y-range shown, so a flat day doesn't look dramatic */
    minSpan?: number;
    format: (v: number | null) => string;
    arrows?: { t: number; deg: number }[];
    /** x labels: hours of one day, or day numbers across a month */
    axis?: 'hours' | 'days';
    height?: number;
    onhover?: (h: { t: number; values: (number | null)[] } | null) => void;
  } = $props();

  let el: HTMLDivElement;

  /** #rrggbb / rgb(r g b) / rgb(r g b / a) → same colour at `alpha` × its own alpha. */
  function withAlpha(c: string, alpha: number): string {
    const hex = /^#([0-9a-f]{6})$/i.exec(c);
    if (hex) {
      const n = parseInt(hex[1]!, 16);
      return `rgb(${n >> 16} ${(n >> 8) & 255} ${n & 255} / ${alpha})`;
    }
    const m = /^rgb\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)\s*(?:\/\s*([\d.]+))?\)$/.exec(c);
    if (m) return `rgb(${m[1]} ${m[2]} ${m[3]} / ${(m[4] ? Number(m[4]) : 1) * alpha})`;
    return c;
  }

  /** Union of all timestamps; each input series → [observed, forecast] columns. */
  function build(): uPlot.AlignedData {
    const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b);
    const idx = new Map(xs.map((x, i) => [x, i]));
    const cols: (number | null)[][] = [];
    for (const s of series) {
      const past = new Array<number | null>(xs.length).fill(null);
      const fut = new Array<number | null>(xs.length).fill(null);
      for (const [t, v] of s.points) {
        const i = idx.get(t)!;
        if (t <= now) past[i] = v;
        if (t >= now) fut[i] = v;
      }
      // Join the two halves at the last observed point so the line is continuous
      const lastPast = past.findLastIndex((v) => v != null);
      const firstFut = fut.findIndex((v) => v != null);
      if (kind === 'line' && lastPast >= 0 && firstFut > lastPast) fut[lastPast] = past[lastPast]!;
      cols.push(past, fut);
    }
    return [xs, ...cols] as uPlot.AlignedData;
  }

  function scaleStroke(colorOf: (v: number) => string, alpha: number) {
    return (u: uPlot) => {
      const { min = 0, max = 10 } = u.scales.y!;
      const y0 = u.valToPos(min, 'y', true);
      const y1 = u.valToPos(max, 'y', true);
      if (!Number.isFinite(y0) || !Number.isFinite(y1) || y0 === y1) return colorOf(min);
      const g = u.ctx.createLinearGradient(0, y0, 0, y1);
      for (let i = 0; i <= 4; i++) {
        const c = colorOf(min + ((max - min) * i) / 4);
        g.addColorStop(i / 4, alpha < 1 ? c.replace(')', ` / ${alpha})`) : c);
      }
      return g;
    };
  }

  function seriesOpts(): uPlot.Series[] {
    const out: uPlot.Series[] = [{}];
    series.forEach((s, si) => {
      for (const part of ['past', 'future'] as const) {
        const alpha = part === 'past' ? 0.5 : 1;
        const primary = si === 0;
        const scaled = s.color === 'temp' ? tempColor : s.color === 'uv' ? uvColor : null;
        const solid = scaled ? null : s.color;
        out.push({
          label: `${s.label} ${part}`,
          spanGaps: true,
          points: { show: false },
          width: kind === 'bars' ? 0 : primary ? 3 : 1.5,
          dash: s.dashed ? [5, 5] : undefined,
          stroke:
            kind === 'bars'
              ? undefined
              : solid
                ? withAlpha(solid, alpha)
                : scaleStroke(scaled!, alpha),
          fill:
            kind === 'bars'
              ? solid
                ? withAlpha(solid, alpha)
                : scaleStroke(scaled!, alpha)
              : undefined,
          paths: kind === 'bars' ? uPlot.paths.bars!({ size: [0.75, 28], align: 0 }) : undefined,
        });
      }
    });
    return out;
  }

  const hourSplits = (_u: uPlot, _ax: number, min: number, max: number) => {
    const out: number[] = [];
    const step = 3 * 3600;
    for (let t = Math.ceil(min / step) * step; t <= max; t += step) out.push(t);
    return out;
  };

  const daySplits = (_u: uPlot, _ax: number, min: number, max: number) => {
    // the 1st and every 5th day, at local noon
    const out: number[] = [];
    for (let t = min + 12 * 3600; t <= max; t += 86400) {
      const d = Number(cphDay.format(new Date(t * 1000)).replace('.', ''));
      if (d === 1 || d % 5 === 0) out.push(t);
    }
    return out;
  };

  const cphHour = new Intl.DateTimeFormat('da-DK', { timeZone: 'Europe/Copenhagen', hour: '2-digit' });
  const cphDay = new Intl.DateTimeFormat('da-DK', { timeZone: 'Europe/Copenhagen', day: 'numeric' });

  $effect(() => {
    const data = build();
    const values = data.slice(1).flat().filter((v): v is number => v != null);
    const lo = values.length ? Math.min(...values) : 0;
    const hi = values.length ? Math.max(...values) : 1;
    const pad = Math.max(1, (hi - lo) * 0.15);
    let y0 = yMin ?? Math.floor(lo - pad);
    let y1 = yMax ?? Math.ceil(hi + pad);
    if (y1 - y0 < minSpan) {
      if (yMin != null) y1 = y0 + minSpan;
      else {
        const mid = (y0 + y1) / 2;
        y0 = Math.floor(mid - minSpan / 2);
        y1 = Math.ceil(mid + minSpan / 2);
      }
    }
    const yRange: [number, number] = [y0, y1];

    const opts: uPlot.Options = {
      width: el.clientWidth || 600,
      height,
      padding: [arrows.length ? 26 : 12, 8, 0, 12],
      legend: { show: false },
      cursor: { y: false, points: { show: false }, drag: { x: false, y: false } },
      scales: { x: { time: false, range: () => range }, y: { range: () => yRange } },
      axes: [
        {
          stroke: 'rgb(255 255 255 / 0.6)',
          grid: { stroke: 'rgb(255 255 255 / 0.08)', width: 1 },
          ticks: { show: false },
          splits: axis === 'days' ? daySplits : hourSplits,
          values: (_u, splits) =>
            splits.map((t) => (axis === 'days' ? cphDay : cphHour).format(new Date(t * 1000)).replace('.', '')),
          font: '11px system-ui',
        },
        {
          side: 1,
          stroke: 'rgb(255 255 255 / 0.6)',
          grid: { stroke: 'rgb(255 255 255 / 0.12)', width: 1, dash: [3, 4] },
          ticks: { show: false },
          values: (_u, splits) => splits.map((v) => format(v)),
          size: 54,
          font: '11px system-ui',
        },
      ],
      series: seriesOpts(),
      hooks: {
        draw: [
          (u) => {
            const ctx = u.ctx;
            const dpr = devicePixelRatio || 1;
            // "Nu" line
            if (now >= range[0] && now <= range[1]) {
              const x = u.valToPos(now, 'x', true);
              ctx.save();
              ctx.strokeStyle = 'rgb(255 255 255 / 0.7)';
              ctx.lineWidth = 1.5 * dpr;
              ctx.setLineDash([3 * dpr, 3 * dpr]);
              ctx.beginPath();
              ctx.moveTo(x, u.bbox.top);
              ctx.lineTo(x, u.bbox.top + u.bbox.height);
              ctx.stroke();
              ctx.setLineDash([]);
              ctx.font = `600 ${11 * dpr}px system-ui`;
              ctx.textAlign = 'center';
              ctx.fillStyle = '#fff';
              // Above the plot — or at its foot when the arrow row is up there
              const ny = arrows.length ? u.bbox.top + u.bbox.height - 6 * dpr : u.bbox.top - 4 * dpr;
              if (arrows.length) {
                const w = ctx.measureText('Nu').width + 8 * dpr;
                ctx.fillStyle = 'rgb(30 40 60 / 0.85)';
                ctx.fillRect(x - w / 2, ny - 11 * dpr, w, 15 * dpr);
                ctx.fillStyle = '#fff';
              }
              ctx.fillText('Nu', x, ny);
              ctx.restore();
            }
            // Wind arrows along the top (pointing where the wind blows to)
            if (arrows.length) {
              ctx.save();
              ctx.fillStyle = 'rgb(255 255 255 / 0.85)';
              for (const a of arrows) {
                if (a.t < range[0] || a.t > range[1]) continue;
                const x = u.valToPos(a.t, 'x', true);
                const y = u.bbox.top - 13 * dpr;
                ctx.translate(x, y);
                ctx.rotate(((a.deg + 180) * Math.PI) / 180);
                ctx.beginPath();
                ctx.moveTo(0, -6 * dpr);
                ctx.lineTo(4.5 * dpr, 5 * dpr);
                ctx.lineTo(0, 2.5 * dpr);
                ctx.lineTo(-4.5 * dpr, 5 * dpr);
                ctx.closePath();
                ctx.fill();
                ctx.setTransform(1, 0, 0, 1, 0, 0);
              }
              ctx.restore();
            }
          },
        ],
        setCursor: [
          (u) => {
            const i = u.cursor.idx;
            if (i == null || !onhover) return onhover?.(null);
            const t = u.data[0][i]!;
            // value per input series: prefer forecast after now, observed before
            const vals = series.map((_, si) => {
              const past = u.data[1 + si * 2]![i] ?? null;
              const fut = u.data[2 + si * 2]![i] ?? null;
              return t <= now ? (past ?? fut) : (fut ?? past);
            });
            onhover({ t, values: vals });
          },
        ],
      },
    };

    const plot = new uPlot(opts, data, el);
    const ro = new ResizeObserver(() => plot.setSize({ width: el.clientWidth, height }));
    ro.observe(el);
    return () => {
      ro.disconnect();
      plot.destroy();
    };
  });
</script>

<div class="chart" bind:this={el}></div>

<style>
  .chart {
    width: 100%;
    touch-action: pan-y;
  }
  .chart :global(.u-cursor-x) {
    border-right: 1px solid rgb(255 255 255 / 0.8);
  }
</style>
