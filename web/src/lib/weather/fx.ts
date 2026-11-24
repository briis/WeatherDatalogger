// Tiny shared state between the two background layers: WeatherFx (2D canvas:
// rain, snow, lightning timing) writes, SkyClouds (WebGL clouds) reads.
// Plain object, not reactive — both read it inside their animation loops.
export const fx = { flash: 0 };
