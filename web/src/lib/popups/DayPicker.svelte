<!-- Apple-style day strip: weekday letter over a date circle; today marked. -->
<script lang="ts">
  import { dayNoon } from '$lib/time';

  let {
    days,
    selected,
    today,
    onselect,
  }: { days: string[]; selected: string; today: string; onselect: (d: string) => void } = $props();

  const wd = new Intl.DateTimeFormat('da-DK', { timeZone: 'Europe/Copenhagen', weekday: 'narrow' });
  const dn = new Intl.DateTimeFormat('da-DK', { timeZone: 'Europe/Copenhagen', day: 'numeric' });
</script>

<div class="days" role="tablist" aria-label="Vælg dag">
  {#each days as d (d)}
    <button
      type="button"
      role="tab"
      aria-selected={d === selected}
      class:sel={d === selected}
      class:today={d === today}
      onclick={() => onselect(d)}
    >
      <span class="w">{wd.format(dayNoon(d)).toUpperCase()}</span>
      <span class="n">{dn.format(dayNoon(d)).replace('.', '')}</span>
    </button>
  {/each}
</div>

<style>
  .days {
    display: flex;
    justify-content: space-between;
    gap: 2px;
    overflow-x: auto;
    scrollbar-width: none;
    margin: 0 -4px 12px;
  }
  .days::-webkit-scrollbar {
    display: none;
  }
  button {
    flex: 1 0 34px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 2px 0;
    border: 0;
    background: none;
    cursor: pointer;
    color: var(--text);
  }
  .w {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-2);
  }
  .n {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    font-size: 16px;
    font-weight: 600;
  }
  .today .n {
    color: #5ac8fa;
  }
  .sel .n {
    background: #fff;
    color: #111;
  }
  button:focus-visible .n {
    outline: 2px solid rgb(255 255 255 / 0.7);
    outline-offset: 2px;
  }
</style>
