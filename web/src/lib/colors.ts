// Colour scales used across widgets: temperature (Apple-style bars), UV,
// EU CAQI. All return CSS colour strings.

type Stop = [value: number, rgb: [number, number, number]];

function scale(stops: Stop[], v: number): string {
  const first = stops[0]!;
  const last = stops[stops.length - 1]!;
  if (v <= first[0]) return rgb(first[1]);
  if (v >= last[0]) return rgb(last[1]);
  for (let i = 1; i < stops.length; i++) {
    const [b, cb] = stops[i]!;
    const [a, ca] = stops[i - 1]!;
    if (v <= b) {
      const t = (v - a) / (b - a);
      return rgb([0, 1, 2].map((k) => ca[k]! + (cb[k]! - ca[k]!) * t) as [number, number, number]);
    }
  }
  return rgb(last[1]);
}

const rgb = ([r, g, b]: [number, number, number]) =>
  `rgb(${Math.round(r)} ${Math.round(g)} ${Math.round(b)})`;

const TEMP: Stop[] = [
  [-15, [94, 92, 230]],
  [-5, [64, 156, 255]],
  [2, [90, 200, 250]],
  [10, [125, 211, 137]],
  [17, [245, 213, 71]],
  [24, [255, 159, 10]],
  [32, [255, 69, 58]],
];

export const tempColor = (t: number) => scale(TEMP, t);

/** CSS linear-gradient spanning low→high on the temperature scale. */
export function tempGradient(low: number, high: number): string {
  const n = 5;
  const parts = Array.from({ length: n }, (_, i) => {
    const t = low + ((high - low) * i) / (n - 1);
    return `${tempColor(t)} ${(i / (n - 1)) * 100}%`;
  });
  return `linear-gradient(to right, ${parts.join(', ')})`;
}

const UV: Stop[] = [
  [0, [52, 199, 89]],
  [3, [255, 214, 10]],
  [6, [255, 159, 10]],
  [8, [255, 69, 58]],
  [11, [191, 90, 242]],
];

/** WHO UV band colour for a UV index. */
export const uvColor = (uv: number) => scale(UV, uv);

/** WHO UV scale, 0–11+. */
export const UV_GRADIENT =
  'linear-gradient(to right, #34c759 0%, #ffd60a 27%, #ff9f0a 50%, #ff453a 73%, #bf5af2 100%)';

/** EU CAQI 0–100+ (Very low → Very high). */
export const CAQI_GRADIENT =
  'linear-gradient(to right, #79bc6a 0%, #bbcf4c 25%, #eec20b 50%, #f29305 75%, #e8416f 100%)';

export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
