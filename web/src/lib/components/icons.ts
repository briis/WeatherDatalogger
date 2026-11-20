// Small original line-icon set (24×24, stroke = currentColor). Kept as path
// data so widgets can render them inline without an icon-font dependency.

export const ICONS = {
  aqi: 'M4 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M5 16h6',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v5l3 2',
  wind: 'M3 9h11a3 3 0 1 0-3-3M3 13h15a3 3 0 1 1-3 3M3 17h7',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z',
  map: 'M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2zM9 4v14M15 6v14',
  sunset: 'M4 18h16M7 14a5 5 0 0 1 10 0M12 4v4M5 8l1.5 1.5M19 8l-1.5 1.5M9 21h6',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  thermometer: 'M10 13.5V5a2 2 0 1 1 4 0v8.5a4 4 0 1 1-4 0ZM12 9v6',
  chart: 'M4 20V4M4 20h16M8 16l4-5 3 3 4-6',
  drop: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z',
  eye: 'M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z',
  humidity: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11ZM9 15h.01M12 12h.01M15 15h.01',
  gauge: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 12l4-4M7 16h10',
  bolt: 'M13 2 4 14h7l-1 8 9-12h-7z',
  close: 'M6 6l12 12M18 6 6 18',
  arrowUp: 'M12 19V5M6 11l6-6 6 6',
  arrowDown: 'M12 5v14M6 13l6 6 6-6',
  location: 'M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12ZM12 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z',
} as const;

export type IconName = keyof typeof ICONS;
