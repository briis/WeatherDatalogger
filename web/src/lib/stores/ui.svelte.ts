// Which popup (if any) is open, plus an optional parameter (e.g. the day a
// 10-day row was tapped on). Opening pushes a history entry, so the phone's
// back gesture closes the popup instead of leaving the site, and the URL
// (#vind, #prognose/2026-11-22) can be shared/bookmarked.

import type { WidgetId } from '$lib/widgets/registry';
import { WIDGETS } from '$lib/widgets/registry';

class UiStore {
  popup = $state<WidgetId | null>(null);
  param = $state<string | null>(null);

  constructor() {
    if (typeof window === 'undefined') return;
    this.#fromHash();
    window.addEventListener('popstate', () => this.#fromHash());
  }

  #fromHash(): void {
    const [slug = '', param] = decodeURIComponent(location.hash.slice(1)).split('/');
    this.popup = WIDGETS.find((w) => w.slug === slug)?.id ?? null;
    this.param = this.popup ? (param ?? null) : null;
  }

  open(id: WidgetId, param: string | null = null): void {
    const w = WIDGETS.find((x) => x.id === id);
    if (!w?.popup) return;
    this.popup = id;
    this.param = param;
    history.pushState({ popup: id }, '', `#${w.slug}${param ? `/${encodeURIComponent(param)}` : ''}`);
  }

  /** Change the parameter of the open popup without a new history entry. */
  setParam(param: string | null): void {
    const w = WIDGETS.find((x) => x.id === this.popup);
    if (!w) return;
    this.param = param;
    history.replaceState(history.state, '', `#${w.slug}${param ? `/${encodeURIComponent(param)}` : ''}`);
  }

  close(): void {
    if (!this.popup) return;
    if (history.state?.popup) history.back();
    else {
      this.popup = null;
      this.param = null;
      history.replaceState(null, '', location.pathname + location.search);
    }
  }
}

export const ui = new UiStore();
