// Thin fetch/WebSocket client. All requests are same-origin relative URLs:
// Caddy (production) or the Vite dev server (development) proxies /api/* to
// the WeatherDatalogger API and adds the X-API-Key header — this code never
// sees the key.

import type { CurrentSnapshot, Daily, Forecast, History } from './types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } });
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText} — ${path}`);
  return (await res.json()) as T;
}

export const api = {
  current: (signal?: AbortSignal) => getJson<CurrentSnapshot>('/api/v1/current', signal),
  forecast: (signal?: AbortSignal) => getJson<Forecast>('/api/v1/forecast', signal),
  history: (hours: number, fields: readonly string[], signal?: AbortSignal) =>
    getJson<History>(
      `/api/v1/history?hours=${hours}&fields=${encodeURIComponent(fields.join(','))}`,
      signal,
    ),
  daily: (days: number, signal?: AbortSignal) =>
    getJson<Daily>(`/api/v1/daily?days=${days}`, signal),
};

/** ws(s)://<this host>/api/v1/ws/current */
export function currentWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/api/v1/ws/current`;
}

/**
 * Parse the API's naive UTC timestamps ("2026-11-20T12:30:00", no offset)
 * as UTC. `new Date()` would otherwise treat them as local time.
 */
export function parseUtc(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  const hasZone = /([zZ]|[+-]\d\d:?\d\d)$/.test(ts);
  const d = new Date(hasZone ? ts : `${ts}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}
