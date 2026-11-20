// The single list of widgets: order on the page, grid size, header and the
// lazily-loaded widget + popup components. Adding a widget = one entry here
// plus its two .svelte files.
//
// Sizes, in grid units (see Grid.svelte). The desktop grid is 6 square-ish
// columns, matching Apple Weather's layout; tablet is 4, phone is 2.
//   small  — 1×1  (Føles som, UV, …)
//   medium — 2×1  (Vind, Måne, Luftkvalitet)
//   wide   — 4×1  (Timeprognose) — full width on phones
//   tall   — 2×3  (10-dages prognose, Vindkort)

import type { Component } from 'svelte';
import type { IconName } from '$lib/components/icons';

export type WidgetSize = 'small' | 'medium' | 'wide' | 'tall';

type Lazy = () => Promise<{ default: Component<{ def: WidgetDef }> }>;

export interface WidgetDef {
  id: string;
  /** URL hash for the open popup, e.g. #vind */
  slug: string;
  title: string;
  icon: IconName;
  size: WidgetSize;
  widget: Lazy;
  popup?: Lazy;
  /** Phase in which the real implementation lands (for the placeholder). */
  phase: number;
}

const placeholder: Lazy = () => import('./Placeholder.svelte');
const popupPlaceholder: Lazy = () => import('../popups/PopupPlaceholder.svelte');

export const WIDGETS = [
  { id: 'airquality', slug: 'luftkvalitet', title: 'Luftkvalitet', icon: 'aqi', size: 'medium' },
  { id: 'hourly', slug: 'timeprognose', title: 'Timeprognose', icon: 'clock', size: 'wide' },
  { id: 'wind', slug: 'vind', title: 'Vind', icon: 'wind', size: 'medium' },
  { id: 'daily', slug: 'prognose', title: '10-dages prognose', icon: 'calendar', size: 'tall' },
  { id: 'map', slug: 'kort', title: 'Vindkort', icon: 'map', size: 'tall' },
  { id: 'moon', slug: 'maane', title: 'Måne', icon: 'moon', size: 'medium' },
  { id: 'sun', slug: 'sol', title: 'Solnedgang', icon: 'sunset', size: 'small' },
  { id: 'uv', slug: 'uv', title: 'UV-indeks', icon: 'sun', size: 'small' },
  { id: 'feelslike', slug: 'foeles-som', title: 'Føles som', icon: 'thermometer', size: 'small' },
  { id: 'averages', slug: 'gennemsnit', title: 'Gennemsnit', icon: 'chart', size: 'small' },
  { id: 'precipitation', slug: 'nedboer', title: 'Nedbør', icon: 'drop', size: 'small' },
  { id: 'visibility', slug: 'sigtbarhed', title: 'Sigtbarhed', icon: 'eye', size: 'small' },
  { id: 'humidity', slug: 'luftfugtighed', title: 'Luftfugtighed', icon: 'humidity', size: 'small' },
  { id: 'pressure', slug: 'lufttryk', title: 'Lufttryk', icon: 'gauge', size: 'small' },
  { id: 'lightning', slug: 'lyn', title: 'Lyn', icon: 'bolt', size: 'small' },
  { id: 'solar', slug: 'solstraaling', title: 'Solstråling', icon: 'sun', size: 'small' },
].map((w) => ({
  ...w,
  phase: 3,
  widget: placeholder,
  popup: popupPlaceholder,
})) as WidgetDef[];

export type WidgetId = (typeof WIDGETS)[number]['id'];
