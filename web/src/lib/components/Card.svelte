<!--
  Frosted-glass widget shell: small uppercase header with icon, then the
  widget body.

  When the widget has a popup, an invisible full-size button sits *behind*
  the content (the "stretched link" pattern) so the whole card is clickable,
  while widgets can still contain their own controls (tabs, scrolling
  strips) — mark those with class="interactive" to lift them above it.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import type { IconName } from './icons';

  let {
    title,
    icon,
    onopen,
    children,
  }: {
    title: string;
    icon: IconName;
    onopen?: () => void;
    children: Snippet;
  } = $props();
</script>

<section class="card" class:clickable={!!onopen}>
  {#if onopen}
    <button class="open" type="button" onclick={onopen} aria-haspopup="dialog">
      <span class="visually-hidden">Vis detaljer: {title}</span>
    </button>
  {/if}
  <header><Icon name={icon} size={13} /> <span>{title}</span></header>
  <div class="body">{@render children()}</div>
</section>

<style>
  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    padding: var(--card-pad);
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    backdrop-filter: blur(var(--card-blur)) saturate(1.4);
    -webkit-backdrop-filter: blur(var(--card-blur)) saturate(1.4);
    overflow: hidden;
    transition:
      background 0.2s,
      transform 0.2s var(--ease);
  }
  .clickable:hover {
    background: var(--card-bg-hover);
  }
  .clickable:active {
    transform: scale(0.985);
  }
  .open {
    position: absolute;
    inset: 0;
    z-index: 0;
    padding: 0;
    border: 0;
    background: none;
    border-radius: inherit;
    cursor: pointer;
  }
  .open:focus-visible {
    outline: 2px solid rgb(255 255 255 / 0.7);
    outline-offset: -2px;
  }
  header,
  .body {
    position: relative;
    pointer-events: none; /* clicks fall through to .open … */
  }
  .body :global(.interactive) {
    pointer-events: auto; /* … except on controls the widget opts in */
  }
  header {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--text-3);
    padding-bottom: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
</style>
