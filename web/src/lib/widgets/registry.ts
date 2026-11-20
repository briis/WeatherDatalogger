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
import { sunInfo } from '$lib/astro';

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
  /** Header text that changes with time (e.g. Solnedgang ↔ Solopgang). */
  liveTitle?: () => string;
  /** Phase in which the real implementation lands (for placeholders). */
  phase: number;
}

const popupPlaceholder: Lazy = () => import('../popups/PopupPlaceholder.svelte');
const small: Lazy = () => import('./StationSmall.svelte');
const conditions: Lazy = () => import('../popups/Conditions.svelte');

/** Sol: the header names the next event, like Apple's. */
function sunTitle(): string {
  const { sunrise, sunset } = sunInfo();
  const now = new Date();
  return now > sunrise && now < sunset ? 'Solnedgang' : 'Solopgang';
}

export const WIDGETS: WidgetDef[] = (
  [
    { id: 'airquality', slug: 'luftkvalitet', title: 'Luftkvalitet', icon: 'aqi', size: 'medium', widget: () => import('./AirQuality.svelte'), popup: () => import('../popups/AirQualityPopup.svelte') },
    { id: 'hourly', slug: 'timeprognose', title: 'Timeprognose', icon: 'clock', size: 'wide', widget: () => import('./Hourly.svelte'), popup: conditions },
    { id: 'wind', slug: 'vind', title: 'Vind', icon: 'wind', size: 'medium', widget: () => import('./Wind.svelte'), popup: conditions },
    { id: 'daily', slug: 'prognose', title: '10-dages prognose', icon: 'calendar', size: 'tall', widget: () => import('./Daily.svelte'), popup: conditions },
    { id: 'radar', slug: 'radar', title: 'Nedbørsradar', icon: 'map', size: 'tall', widget: () => import('./Radar.svelte') },
    { id: 'moon', slug: 'maane', title: 'Måne', icon: 'moon', size: 'medium', widget: () => import('./Moon.svelte'), popup: () => import('../popups/MoonPopup.svelte') },
    { id: 'sun', slug: 'sol', title: 'Solnedgang', liveTitle: sunTitle, icon: 'sunset', size: 'small', widget: () => import('./Sun.svelte'), popup: () => import('../popups/SunPopup.svelte') },
    { id: 'uv', slug: 'uv', title: 'UV-indeks', icon: 'sun', size: 'small', widget: () => import('./Uv.svelte'), popup: conditions },
    { id: 'feelslike', slug: 'foeles-som', title: 'Føles som', icon: 'thermometer', size: 'small', widget: small, popup: conditions },
    { id: 'averages', slug: 'gennemsnit', title: 'Gennemsnit', icon: 'chart', size: 'small', widget: () => import('./Averages.svelte'), popup: () => import('../popups/AveragesPopup.svelte') },
    { id: 'precipitation', slug: 'nedboer', title: 'Nedbør', icon: 'drop', size: 'small', widget: small, popup: conditions },
    { id: 'visibility', slug: 'sigtbarhed', title: 'Sigtbarhed', icon: 'eye', size: 'small', widget: small, popup: conditions },
    { id: 'humidity', slug: 'luftfugtighed', title: 'Luftfugtighed', icon: 'humidity', size: 'small', widget: small, popup: conditions },
    { id: 'pressure', slug: 'lufttryk', title: 'Lufttryk', icon: 'gauge', size: 'small', widget: () => import('./Pressure.svelte'), popup: conditions },
    { id: 'lightning', slug: 'lyn', title: 'Lyn', icon: 'bolt', size: 'small', widget: small, popup: () => import('../popups/LightningPopup.svelte') },
    { id: 'solar', slug: 'solstraaling', title: 'Solstråling', icon: 'sun', size: 'small', widget: small, popup: conditions },
  ] satisfies Omit<WidgetDef, 'popup' | 'phase'>[] | Partial<WidgetDef>[]
).map((w) => ({ phase: 4, popup: popupPlaceholder, ...w }) as WidgetDef);

export type WidgetId = WidgetDef['id'];
