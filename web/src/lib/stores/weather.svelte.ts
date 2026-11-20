// Global reactive state (Svelte 5 runes).
//
//  - `live`     — current observations, pushed over WebSocket, with REST as
//                 the first paint and as a fallback while the socket is down
//  - `forecast` — Open-Meteo forecast, polled (it only changes when the
//                 openmeteo-datalogger fetches, at most every few minutes)
//
// Both resume immediately when the tab becomes visible again, so a phone
// that wakes up from sleep doesn't show stale data until the next tick.

import { api, currentWsUrl } from '$lib/api/client';
import type { CurrentSnapshot, Forecast } from '$lib/api/types';

export type LinkStatus = 'connecting' | 'live' | 'polling' | 'offline';

const WS_BACKOFF_MS = [1_000, 2_000, 5_000, 10_000, 30_000];
const REST_FALLBACK_MS = 15_000;
const FORECAST_REFRESH_MS = 10 * 60_000;

class LiveStore {
  snapshot = $state<CurrentSnapshot | null>(null);
  status = $state<LinkStatus>('connecting');
  /** Browser time of the last successful message (WS or REST). */
  receivedAt = $state<Date | null>(null);

  #ws: WebSocket | null = null;
  #attempt = 0;
  #reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  #pollTimer: ReturnType<typeof setInterval> | undefined;
  #started = false;

  get current() {
    return this.snapshot?.combined_realtime ?? null;
  }

  get stats() {
    return this.snapshot?.combined_realtime_stats ?? null;
  }

  start(): void {
    if (this.#started) return;
    this.#started = true;
    void this.#fetchOnce();
    this.#connect();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && this.#ws?.readyState !== WebSocket.OPEN) {
        this.#attempt = 0;
        clearTimeout(this.#reconnectTimer);
        void this.#fetchOnce();
        this.#connect();
      }
    });
  }

  #accept(snap: CurrentSnapshot): void {
    this.snapshot = snap;
    this.receivedAt = new Date();
  }

  async #fetchOnce(): Promise<void> {
    try {
      this.#accept(await api.current());
      if (this.status === 'offline') this.status = 'polling';
    } catch {
      if (this.status !== 'live') this.status = 'offline';
    }
  }

  #connect(): void {
    this.#ws?.close();
    const ws = new WebSocket(currentWsUrl());
    this.#ws = ws;
    if (this.status !== 'live') this.status = this.snapshot ? 'polling' : 'connecting';

    ws.onopen = () => {
      this.#attempt = 0;
      this.status = 'live';
      clearInterval(this.#pollTimer);
      this.#pollTimer = undefined;
    };
    ws.onmessage = (ev: MessageEvent<string>) => {
      try {
        this.#accept(JSON.parse(ev.data) as CurrentSnapshot);
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      if (this.#ws !== ws) return; // superseded by a newer socket
      this.status = this.snapshot ? 'polling' : 'offline';
      // Keep data flowing over REST while the socket is down
      this.#pollTimer ??= setInterval(() => void this.#fetchOnce(), REST_FALLBACK_MS);
      const delay = WS_BACKOFF_MS[Math.min(this.#attempt++, WS_BACKOFF_MS.length - 1)];
      this.#reconnectTimer = setTimeout(() => this.#connect(), delay);
    };
  }
}

class ForecastStore {
  data = $state<Forecast | null>(null);
  error = $state<string | null>(null);
  #started = false;

  get current() {
    return this.data?.current ?? null;
  }
  get hourly() {
    return this.data?.hourly ?? [];
  }
  get daily() {
    return this.data?.daily ?? [];
  }

  start(): void {
    if (this.#started) return;
    this.#started = true;
    void this.refresh();
    setInterval(() => void this.refresh(), FORECAST_REFRESH_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void this.refresh();
    });
  }

  async refresh(): Promise<void> {
    try {
      this.data = await api.forecast();
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }
}

export const live = new LiveStore();
export const forecast = new ForecastStore();

/**
 * A once-per-key cached async loader for popup data (history/daily), so
 * reopening a popup is instant and doesn't re-query.
 */
const resourceCache = new Map<string, { at: number; promise: Promise<unknown> }>();

export function cachedLoad<T>(key: string, load: () => Promise<T>, ttlMs = 60_000): Promise<T> {
  const hit = resourceCache.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return hit.promise as Promise<T>;
  const promise = load();
  resourceCache.set(key, { at: Date.now(), promise });
  promise.catch(() => resourceCache.delete(key));
  return promise;
}
