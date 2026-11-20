// DMI radar frames rendered by web/radar/radar_worker.py, served by Caddy as
// /radar/frames.json + /radar/<time>.png. Polled every 2 minutes (the worker
// runs every 5; new frames appear ~7 min after their scan time).

import { parseUtc } from '$lib/api/client';

export interface RadarFrame {
  time: Date;
  url: string;
  /** true for the extrapolated frames after the newest scan */
  forecast?: boolean;
}

/** frames.json "nowcast" — computed by the worker for the station. */
export interface Nowcast {
  time?: string;
  rain_rate_mmh?: number | null;
  nearest_rain_km?: number | null;
  nearest_rain_direction?: string | null;
  motion_speed_kmh?: number | null;
  motion_from?: string | null;
  /** 0 = raining now, null = nothing on its way (within 2 h) */
  rain_expected_in_min?: number | null;
}

interface Manifest {
  generated_at: string;
  bounds: [[number, number], [number, number]];
  frames: { time: string; url: string }[];
  forecast?: { time: string; url: string }[];
  nowcast?: Nowcast;
}

const REFRESH_MS = 2 * 60_000;

class RadarStore {
  bounds = $state<[[number, number], [number, number]] | null>(null);
  frames = $state<RadarFrame[]>([]);
  forecast = $state<RadarFrame[]>([]);
  nowcast = $state<Nowcast | null>(null);
  /** Rain rate at the station from the newest frame (mm/h), if any. */
  rainNow = $state<number | null>(null);
  error = $state<string | null>(null);
  #started = false;

  get latest(): RadarFrame | null {
    return this.frames.at(-1) ?? null;
  }

  /** Short Danish nowcast sentence for the station, or null if nothing useful. */
  get outlook(): string | null {
    const n = this.nowcast;
    const latest = this.latest;
    // Only trust a nowcast from a reasonably fresh frame
    if (!n || !latest || Date.now() - latest.time.getTime() > 45 * 60_000) return null;
    const eta = n.rain_expected_in_min;
    if ((n.rain_rate_mmh ?? 0) >= 0.2 || eta === 0) return 'Det regner ved stationen ifølge radaren.';
    if (eta != null && eta > 0) {
      // the frame is already a few minutes old when we see it
      const left = Math.max(5, eta - Math.round((Date.now() - latest.time.getTime()) / 60_000));
      const rounded = Math.round(left / 5) * 5;
      return `Regn ventes om ca. ${rounded} min.${n.motion_from ? ` Bygerne kommer fra ${n.motion_from}.` : ''}`;
    }
    if (n.nearest_rain_km != null && n.nearest_rain_km <= 60) {
      return `Nærmeste nedbør ${Math.round(n.nearest_rain_km)} km mod ${n.nearest_rain_direction ?? '?'}${
        n.motion_from ? `, på vej fra ${n.motion_from}` : ''
      } — ikke mod stationen.`;
    }
    return null;
  }

  start(): void {
    if (this.#started) return;
    this.#started = true;
    void this.refresh();
    setInterval(() => void this.refresh(), REFRESH_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void this.refresh();
    });
  }

  async refresh(): Promise<void> {
    try {
      const res = await fetch('/radar/frames.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error(`${res.status}`);
      const m = (await res.json()) as Manifest;
      this.bounds = m.bounds;
      this.frames = m.frames
        .map((f) => ({ time: parseUtc(f.time), url: f.url }))
        .filter((f): f is RadarFrame => f.time != null);
      this.forecast = (m.forecast ?? []).flatMap((f): RadarFrame[] => {
        const time = parseUtc(f.time);
        return time ? [{ time, url: f.url, forecast: true }] : [];
      });
      this.nowcast = m.nowcast ?? null;
      this.rainNow = m.nowcast?.rain_rate_mmh ?? null;
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }
}

export const radar = new RadarStore();
