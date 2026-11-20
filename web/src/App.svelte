<script lang="ts">
  import { onMount } from 'svelte';
  import Grid from '$lib/components/Grid.svelte';
  import Hero from '$lib/components/Hero.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import ConnectionBanner from '$lib/components/ConnectionBanner.svelte';
  import Sky from '$lib/components/Sky.svelte';
  import StatusFooter from '$lib/components/StatusFooter.svelte';
  import { forecast, live } from '$lib/stores/weather.svelte';
  import { ui } from '$lib/stores/ui.svelte';
  import { WIDGETS } from '$lib/widgets/registry';

  onMount(() => {
    live.start();
    forecast.start();
  });

  const openDef = $derived(WIDGETS.find((w) => w.id === ui.popup));
</script>

<Sky />

<main>
  <Hero />
  <ConnectionBanner />
  <Grid />
  <StatusFooter />
</main>

{#if openDef?.popup}
  <Modal title={openDef.title} icon={openDef.icon} size={openDef.popupSize} onclose={() => ui.close()}>
    {#await openDef.popup() then mod}
      <mod.default def={openDef} />
    {/await}
  </Modal>
{/if}

<style>
  main {
    position: relative;
    z-index: 1;
    max-width: var(--page-max);
    margin: 0 auto;
    padding: env(safe-area-inset-top) max(12px, env(safe-area-inset-right)) 0
      max(12px, env(safe-area-inset-left));
  }
  @media (min-width: 640px) {
    main {
      padding-inline: 24px;
    }
  }
</style>
