<!--
  Popup shell, built on the native <dialog> (focus trap, Esc, inert page for
  free). Bottom sheet on phones, centred panel on larger screens. Closing is
  routed through ui.close() so the history entry pushed on open is popped.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import type { IconName } from './icons';

  let {
    title,
    icon,
    onclose,
    size = 'normal',
    children,
  }: {
    title: string;
    icon: IconName;
    onclose: () => void;
    size?: 'normal' | 'large';
    children: Snippet;
  } = $props();

  let dialog: HTMLDialogElement;

  $effect(() => {
    dialog.showModal();
    return () => dialog.close();
  });

  function onBackdrop(e: MouseEvent) {
    if (e.target === dialog) onclose();
  }
</script>

<dialog
  bind:this={dialog}
  onclick={onBackdrop}
  oncancel={(e) => {
    e.preventDefault();
    onclose();
  }}
  aria-labelledby="popup-title"
>
  <div class="sheet" class:large={size === 'large'}>
    <header>
      <h2 id="popup-title"><Icon name={icon} size={18} /> {title}</h2>
      <button class="close" type="button" onclick={onclose} aria-label="Luk">
        <Icon name="close" size={16} stroke={2.5} />
      </button>
    </header>
    <div class="content">{@render children()}</div>
  </div>
</dialog>

<style>
  dialog {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text);
    max-width: none;
    max-height: none;
    width: 100%;
    height: 100%;
    margin: 0;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    overflow: hidden;
  }
  dialog::backdrop {
    background: rgb(0 0 0 / 0.35);
    backdrop-filter: blur(4px);
    animation: fade 0.25s ease-out;
  }
  .sheet {
    width: 100%;
    max-height: 92dvh;
    display: flex;
    flex-direction: column;
    background: var(--sheet-bg);
    backdrop-filter: blur(40px) saturate(1.6);
    -webkit-backdrop-filter: blur(40px) saturate(1.6);
    border-radius: 20px 20px 0 0;
    border: 1px solid var(--card-border);
    box-shadow: 0 20px 60px rgb(0 0 0 / 0.4);
    animation: slide-up 0.4s var(--ease);
    padding-bottom: env(safe-area-inset-bottom);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 16px 8px 20px;
  }
  h2 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-size: 17px;
    font-weight: 600;
  }
  .close {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    border: 0;
    background: rgb(255 255 255 / 0.12);
    cursor: pointer;
  }
  .close:hover {
    background: rgb(255 255 255 / 0.2);
  }
  .content {
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 8px 20px 24px;
  }

  /* Large: near full-screen, content fills the height (maps) */
  .sheet.large {
    height: 94dvh;
    max-height: none;
  }
  .sheet.large .content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 0 12px 12px;
  }

  @media (min-width: 700px) {
    dialog {
      align-items: center;
    }
    .sheet {
      width: min(720px, calc(100% - 48px));
      max-height: min(86dvh, 860px);
      border-radius: 20px;
      animation: pop 0.3s var(--ease);
    }
    .sheet.large {
      width: min(1200px, calc(100% - 48px));
      height: min(90dvh, 1000px);
      max-height: none;
    }
  }

  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes slide-up {
    from {
      transform: translateY(100%);
    }
  }
  @keyframes pop {
    from {
      transform: scale(0.96);
      opacity: 0;
    }
  }
</style>
