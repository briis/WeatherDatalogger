<!--
  Responsive widget grid. Columns: 2 (phone) → 4 (tablet) → 6 (desktop);
  `grid-auto-flow: dense` back-fills gaps so mixed sizes pack like Apple
  Weather. Each widget body is lazy-loaded.
-->
<script lang="ts">
  import Card from './Card.svelte';
  import { WIDGETS } from '$lib/widgets/registry';
  import { ui } from '$lib/stores/ui.svelte';
</script>

<div class="grid">
  {#each WIDGETS as def (def.id)}
    <div class="cell {def.size}">
      <Card
        title={def.title}
        icon={def.icon}
        onopen={def.popup ? () => ui.open(def.id) : undefined}
      >
        {#await def.widget() then mod}
          <mod.default {def} />
        {/await}
      </Card>
    </div>
  {/each}
</div>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-auto-rows: minmax(150px, auto);
    grid-auto-flow: row dense;
    gap: var(--gap);
  }
  .cell {
    min-width: 0;
  }
  .medium,
  .wide {
    grid-column: span 2;
  }
  .tall {
    grid-column: span 2;
    grid-row: span 3;
  }

  @media (min-width: 640px) {
    .grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .wide {
      grid-column: span 4;
    }
  }

  @media (min-width: 1000px) {
    .grid {
      grid-template-columns: repeat(6, minmax(0, 1fr));
    }
  }
</style>
