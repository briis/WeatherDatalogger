// Which popup (if any) is open. Opening a popup pushes a history entry, so
// the phone's back gesture/button closes it instead of leaving the site, and
// a popup URL (#vind) can be shared/bookmarked.

import type { WidgetId } from '$lib/widgets/registry';
import { WIDGETS } from '$lib/widgets/registry';

class UiStore {
  popup = $state<WidgetId | null>(null);

  constructor() {
    if (typeof window === 'undefined') return;
    this.popup = this.#fromHash();
    window.addEventListener('popstate', () => {
      this.popup = this.#fromHash();
    });
  }

  #fromHash(): WidgetId | null {
    const slug = decodeURIComponent(location.hash.slice(1));
    return WIDGETS.find((w) => w.slug === slug)?.id ?? null;
  }

  open(id: WidgetId): void {
    const w = WIDGETS.find((x) => x.id === id);
    if (!w?.popup) return;
    this.popup = id;
    history.pushState({ popup: id }, '', `#${w.slug}`);
  }

  close(): void {
    if (!this.popup) return;
    if (history.state?.popup) history.back();
    else {
      this.popup = null;
      history.replaceState(null, '', location.pathname + location.search);
    }
  }
}

export const ui = new UiStore();
