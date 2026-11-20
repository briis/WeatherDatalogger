<script lang="ts">
  import { ICONS, type IconName } from './icons';

  let { name, size = 14, stroke = 2 }: { name: IconName; size?: number; stroke?: number } =
    $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={ICONS[name]} />
</svg>
