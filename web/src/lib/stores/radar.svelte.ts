// DMI radar frames rendered by web/radar/radar_worker.py, served by Caddy as
// /radar/frames.json + /radar/<time>.png. Polled every 2 minutes (the worker
// runs every 5; new frames appear ~7 min after their scan time).

import { parseUtc } from '$lib/api/client';

export interface RadarFrame {
  time: Date;
  url: string;
}

interface Manifest {
  generated_at: string;
  bounds: [[number, number], [number, number]];
  frames: { time: string; url: string }[];
  nowcast?: { time?: string; rain_rate_mmh?: number | null };
}

const REFRESH_MS = 2 * 60_000;

class RadarStore {
  bounds = $state<[[number, number], [number, number]] | null>(null);
  frames = $state<RadarFrame[]>([]);
  /** Rain rate at the station from the newest frame (mm/h), if any. */
  rainNow = $state<number | null>(null);
  error = $state<string | null>(null);
  #started = false;

  get latest(): RadarFrame | null {
    return this.frames.at(-1) ?? null;
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
      this.rainNow = m.nowcast?.rain_rate_mmh ?? null;
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }
}

export const radar = new RadarStore();
