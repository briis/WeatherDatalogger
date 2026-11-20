<!--
  Frosted-glass widget shell: small uppercase header with icon, then the
  widget body. The whole card is a button when the widget has a popup.
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

{#if onopen}
  <button class="card interactive" type="button" onclick={onopen} aria-haspopup="dialog">
    <header><Icon name={icon} size={13} /> <span>{title}</span></header>
    <div class="body">{@render children()}</div>
  </button>
{:else}
  <section class="card">
    <header><Icon name={icon} size={13} /> <span>{title}</span></header>
    <div class="body">{@render children()}</div>
  </section>
{/if}

<style>
  .card {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    padding: var(--card-pad);
    text-align: left;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    backdrop-filter: blur(var(--card-blur)) saturate(1.4);
    -webkit-backdrop-filter: blur(var(--card-blur)) saturate(1.4);
    overflow: hidden;
  }
  .interactive {
    cursor: pointer;
    transition:
      background 0.2s,
      transform 0.2s var(--ease);
  }
  .interactive:hover {
    background: var(--card-bg-hover);
  }
  .interactive:active {
    transform: scale(0.985);
  }
  .interactive:focus-visible {
    outline: 2px solid rgb(255 255 255 / 0.7);
    outline-offset: 2px;
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
  }
  .body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
</style>
