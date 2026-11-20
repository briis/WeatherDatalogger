<!--
  A drawn moon for a given illumination/phase (northern hemisphere:
  waxing = lit on the right). Unique ids per instance, so many can share a
  page (the month calendar in the moon popup).
-->
<script lang="ts">
  let {
    illumination,
    waxing,
    size = 96,
    label = '',
  }: { illumination: number; waxing: boolean; size?: number; label?: string } = $props();

  const uid = `m${Math.random().toString(36).slice(2, 8)}`;
  const R = 40;

  // Terminator: an ellipse whose x-radius goes R → 0 → R as illumination 0 → ½ → 1
  const path = $derived.by(() => {
    const f = illumination;
    const rx = Math.abs(1 - 2 * f) * R;
    const outerSweep = waxing ? 1 : 0;
    const innerSweep = f > 0.5 ? (waxing ? 1 : 0) : waxing ? 0 : 1;
    return `M50 ${50 - R} A${R} ${R} 0 0 ${outerSweep} 50 ${50 + R} A${rx} ${R} 0 0 ${innerSweep} 50 ${50 - R} Z`;
  });
</script>

<svg
  viewBox="0 0 100 100"
  width={size}
  height={size}
  role={label ? 'img' : undefined}
  aria-label={label || undefined}
  aria-hidden={label ? undefined : 'true'}
>
  <defs>
    <radialGradient id="{uid}g" cx="45%" cy="40%" r="65%">
      <stop offset="0%" stop-color="#f4f4f6" />
      <stop offset="100%" stop-color="#b9bcc4" />
    </radialGradient>
    <clipPath id="{uid}c"><path d={path} /></clipPath>
  </defs>
  <circle cx="50" cy="50" r={R} fill="rgb(0 0 0 / 0.35)" />
  <path d={path} fill="url(#{uid}g)" />
  <g fill="rgb(120 124 135 / 0.28)" clip-path="url(#{uid}c)">
    <circle cx="40" cy="38" r="7" /><circle cx="58" cy="46" r="9" /><circle cx="46" cy="62" r="5" />
  </g>
</svg>
