// Danish texts and value → label mappings. Kept in one place so wording can
// be tuned without touching components.

import type { WeatherCondition } from '$lib/api/types';

export const SITE = {
  /** Shown in the hero — your station, not a selectable location. */
  locationName: 'Gundsømagle',
  locationSub: 'Min station',
  title: 'Vejret i Gundsømagle',
};

export const CONDITION: Record<WeatherCondition, string> = {
  'clear-night': 'Klart',
  cloudy: 'Overskyet',
  exceptional: 'Usædvanligt vejr',
  fog: 'Tåge',
  hail: 'Hagl',
  lightning: 'Torden',
  'lightning-rainy': 'Torden og regn',
  partlycloudy: 'Delvis skyet',
  pouring: 'Kraftig regn',
  rainy: 'Regn',
  snowy: 'Sne',
  'snowy-rainy': 'Slud',
  sunny: 'Solrigt',
  windy: 'Blæsende',
  'windy-variant': 'Blæsende og skyet',
};

export const conditionText = (c: WeatherCondition | null | undefined) =>
  c ? (CONDITION[c] ?? c) : '';

const COMPASS_16 = [
  'N', 'NNØ', 'NØ', 'ØNØ', 'Ø', 'ØSØ', 'SØ', 'SSØ',
  'S', 'SSV', 'SV', 'VSV', 'V', 'VNV', 'NV', 'NNV',
] as const;

/** 296 → "VNV" */
export function compass(deg: number | null | undefined): string {
  if (deg == null || !Number.isFinite(deg)) return '–';
  const i = Math.round((((deg % 360) + 360) % 360) / 22.5) % 16;
  return COMPASS_16[i] ?? '–';
}

export const BEAUFORT = [
  'Stille', 'Næsten stille', 'Svag vind', 'Let vind', 'Jævn vind', 'Frisk vind',
  'Hård vind', 'Stiv kuling', 'Hård kuling', 'Stormende kuling', 'Storm',
  'Stærk storm', 'Orkan',
] as const;

const BEAUFORT_LIMITS_MS = [0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7];

export function beaufort(ms: number | null | undefined): { force: number; label: string } | null {
  if (ms == null || !Number.isFinite(ms)) return null;
  let force = BEAUFORT_LIMITS_MS.findIndex((limit) => ms < limit);
  if (force === -1) force = 12;
  return { force, label: BEAUFORT[force] ?? '' };
}

export const PRESSURE_TREND: Record<string, string> = {
  Rising: 'Stigende',
  Steady: 'Stabilt',
  Falling: 'Faldende',
};

/** WHO/WMO UV index bands. */
export function uvLevel(uv: number | null | undefined): string {
  if (uv == null) return '–';
  if (uv < 3) return 'Lav';
  if (uv < 6) return 'Moderat';
  if (uv < 8) return 'Høj';
  if (uv < 11) return 'Meget høj';
  return 'Ekstrem';
}

/** EU CAQI (CITEAIR) bands — 0-25-50-75-100+. */
export function caqiLevel(caqi: number | null | undefined): string {
  if (caqi == null) return '–';
  if (caqi < 25) return 'Meget god';
  if (caqi < 50) return 'God';
  if (caqi < 75) return 'Middel';
  if (caqi < 100) return 'Dårlig';
  return 'Meget dårlig';
}

/** SunCalc phase fraction (0 = new, 0.5 = full) → Danish phase name. */
export function moonPhaseName(phase: number): string {
  const names = [
    'Nymåne', 'Tiltagende segl', 'Første kvarter', 'Tiltagende måne',
    'Fuldmåne', 'Aftagende måne', 'Sidste kvarter', 'Aftagende segl',
  ];
  return names[Math.round(phase * 8) % 8] ?? '';
}
