// Variables used by Scriptable.
// icon-color: blue; icon-glyph: cloud-sun;
//
// Vejret i Gundsømagle — iOS widget for Scriptable (https://scriptable.app)
// Data: vejr.briis.com (station via WeatherDatalogger API, Open-Meteo
// forecast, DMI radar nowcast). Tap opens the website.
//
// Sizes: small, medium, large + lock screen (rectangular, circular, inline).
// Widget parameter (long-press → Edit widget → Parameter): optional base URL.

const BASE = (args.widgetParameter || "https://vejr.briis.com").replace(/\/$/, "");
const PLACE = "Gundsømagle";
const fm = FileManager.local();
const CACHE = fm.joinPath(fm.cacheDirectory(), "vejr-widget.json");

// ── Data ────────────────────────────────────────────────────────────────
async function getJSON(path) {
  const r = new Request(BASE + path);
  r.timeoutInterval = 15;
  return r.loadJSON();
}

async function load() {
  try {
    const [cur, fc, radar] = await Promise.all([
      getJSON("/api/v1/current"),
      getJSON("/api/v1/forecast"),
      getJSON("/radar/frames.json").catch(() => null),
    ]);
    const data = { cur, fc, radar, fetched: Date.now() };
    fm.writeString(CACHE, JSON.stringify(data));
    return data;
  } catch (e) {
    if (fm.fileExists(CACHE)) {
      const data = JSON.parse(fm.readString(CACHE));
      data.stale = true;
      return data;
    }
    throw e;
  }
}

const parseUtc = (ts) => {
  if (!ts) return null;
  const d = new Date(/([zZ]|[+-]\d\d:?\d\d)$/.test(ts) ? ts : ts + "Z");
  return isNaN(d) ? null : d;
};
const r0 = (v) => (v == null ? "–" : Math.round(v) + "°");

// ── Condition → text, symbol, sky ───────────────────────────────────────
const TEXT = {
  "clear-night": "Klart", cloudy: "Overskyet", exceptional: "Usædvanligt vejr",
  fog: "Tåge", hail: "Hagl", lightning: "Torden", "lightning-rainy": "Torden og regn",
  partlycloudy: "Delvis skyet", pouring: "Kraftig regn", rainy: "Regn", snowy: "Sne",
  "snowy-rainy": "Slud", sunny: "Solrigt", windy: "Blæsende", "windy-variant": "Blæsende og skyet",
};

function symbolName(c, night) {
  switch (c) {
    case "sunny": return night ? "moon.stars.fill" : "sun.max.fill";
    case "clear-night": return "moon.stars.fill";
    case "partlycloudy": return night ? "cloud.moon.fill" : "cloud.sun.fill";
    case "cloudy": return "cloud.fill";
    case "fog": return "cloud.fog.fill";
    case "rainy": return "cloud.rain.fill";
    case "pouring": return "cloud.heavyrain.fill";
    case "lightning": return "cloud.bolt.fill";
    case "lightning-rainy": return "cloud.bolt.rain.fill";
    case "snowy": return "cloud.snow.fill";
    case "snowy-rainy": return "cloud.sleet.fill";
    case "hail": return "cloud.hail.fill";
    case "windy": case "windy-variant": return "wind";
    default: return "exclamationmark.triangle.fill";
  }
}

function family(c) {
  if (c === "sunny" || c === "clear-night") return "clear";
  if (c === "partlycloudy") return "partly";
  if (c === "rainy" || c === "pouring") return "rain";
  if (c === "snowy" || c === "snowy-rainy" || c === "hail") return "snow";
  if (c === "fog") return "fog";
  if (c === "lightning" || c === "lightning-rainy") return "storm";
  return "cloudy";
}

// Same palette as the website (Sky.svelte)
const SKIES = {
  day: { clear: ["#2a62a8", "#8cb7e0"], partly: ["#3a6aa4", "#9dbbd9"], cloudy: ["#5b6d82", "#a4b1bf"], rain: ["#3b4a5d", "#6f7f90"], snow: ["#6b7d95", "#c3ced9"], fog: ["#7c8692", "#bcc2ca"], storm: ["#252d3a", "#566070"] },
  dawn: { clear: ["#3c5d93", "#f0b27a"], partly: ["#4a5f8a", "#d9a582"], cloudy: ["#58627a", "#a99a96"], rain: ["#3d4659", "#7a7a84"], snow: ["#5f6c87", "#c4b8b8"], fog: ["#6f7585", "#b9adab"], storm: ["#262b38", "#5b5560"] },
  dusk: { clear: ["#2d3f78", "#e8956a"], partly: ["#36446f", "#c98a73"], cloudy: ["#4a5068", "#93807f"], rain: ["#323a4c", "#6a6670"], snow: ["#4f5874", "#ab9fa3"], fog: ["#5d6273", "#9e9294"], storm: ["#1f2330", "#4c4652"] },
  night: { clear: ["#07132a", "#1f3d68"], partly: ["#0f1b31", "#2b4366"], cloudy: ["#1a2230", "#394454"], rain: ["#141b26", "#313b4a"], snow: ["#263248", "#536276"], fog: ["#252b34", "#48505b"], storm: ["#0d1118", "#29303b"] },
};

function timeOfDay(now, rise, set) {
  if (!rise || !set) { const h = now.getHours(); return h >= 7 && h < 17 ? "day" : "night"; }
  const m = 45 * 60e3;
  if (Math.abs(now - rise) < m) return "dawn";
  if (Math.abs(now - set) < m) return "dusk";
  return now > rise && now < set ? "day" : "night";
}

// Radar outlook — same rules as the website's Nedbør widget
function outlook(radar, short) {
  const n = radar && radar.nowcast;
  const frames = (radar && radar.frames) || [];
  const latest = frames.length ? parseUtc(frames[frames.length - 1].time) : null;
  if (!n || !latest || Date.now() - latest > 45 * 60e3) return null;
  const eta = n.rain_expected_in_min;
  if ((n.rain_rate_mmh || 0) >= 0.2 || eta === 0) return short ? "Regner nu" : "Det regner ved stationen";
  if (eta != null && eta > 0) {
    const left = Math.max(5, eta - Math.round((Date.now() - latest) / 60e3));
    const mins = Math.round(left / 5) * 5;
    return short ? `Regn om ${mins} min` : `Regn ventes om ca. ${mins} min.`;
  }
  return null;
}

// ── Model ───────────────────────────────────────────────────────────────
function model(d) {
  const c = (d.cur && d.cur.combined_realtime) || {};
  const s = (d.cur && d.cur.combined_realtime_stats) || {};
  const f = (d.fc && d.fc.current) || {};
  const now = new Date();
  const rise = parseUtc(f.sunrise), set = parseUtc(f.sunset);
  const tod = timeOfDay(now, rise, set);
  const night = tod === "night";
  let cond = f.weather_condition || "cloudy";
  if ((c.rain_rate_mmh || 0) > 0 && family(cond) !== "storm" && family(cond) !== "snow")
    cond = c.rain_rate_mmh >= 4 ? "pouring" : "rainy";
  if (night && cond === "sunny") cond = "clear-night";

  const hours = ((d.fc && d.fc.hourly) || [])
    .map((h) => ({ t: parseUtc(h.forecast_time), temp: h.temperature_c, cond: h.weather_condition, pop: h.precipitation_probability_pct }))
    .filter((h) => h.t && h.t > now - 30 * 60e3)
    .slice(0, 5);
  const todayKey = now.toISOString().slice(0, 10);
  const days = ((d.fc && d.fc.daily) || [])
    .map((x) => ({ key: x.forecast_time.slice(0, 10), hi: x.temperature_high_c, lo: x.temperature_low_c, cond: x.weather_condition, pop: x.precipitation_probability_pct }))
    .filter((x) => x.key >= todayKey)
    .slice(0, 6);

  return {
    temp: c.air_temperature_c ?? f.temperature_c,
    feels: c.feels_like_c,
    hi: s.air_temp_high_today ?? f.temperature_high_c,
    lo: s.air_temp_low_today ?? f.temperature_low_c,
    cond, tod, night,
    sky: SKIES[tod][family(cond)],
    hours, days,
    outlookLong: outlook(d.radar, false),
    outlookShort: outlook(d.radar, true),
    stale: !!d.stale,
  };
}

// ── Drawing helpers ─────────────────────────────────────────────────────
// Small text and icons are scaled up on the home screen; the big temperature
// and the lock-screen widgets keep their sizes. Tweak SCALE to taste.
const SCALE = 1.2;
let S = 1;
const sz = (n) => (n <= 18 ? Math.round(n * S) : n);
const WHITE = Color.white();
const DIM = new Color("#ffffff", 0.75);

function txt(stack, s, size, weight = "regular", color = WHITE) {
  size = sz(size);
  const t = stack.addText(String(s));
  t.font = weight === "light" ? Font.lightSystemFont(size)
    : weight === "medium" ? Font.mediumSystemFont(size)
    : weight === "semibold" ? Font.semiboldSystemFont(size)
    : Font.systemFont(size);
  t.textColor = color;
  t.lineLimit = 1;
  t.minimumScaleFactor = 0.6;
  return t;
}

function sym(stack, name, size, color = WHITE) {
  size = sz(size);
  const sf = SFSymbol.named(name) || SFSymbol.named("cloud.fill");
  sf.applyFont(Font.systemFont(size));
  const img = stack.addImage(sf.image);
  img.imageSize = new Size(size * 1.2, size * 1.2);
  img.tintColor = color;
  img.resizable = true;
  return img;
}

const hourLabel = (d) => String(d.getHours()).padStart(2, "0");
const DAYS = ["Søn", "Man", "Tir", "Ons", "Tor", "Fre", "Lør"];
const dayLabel = (key, i) => (i === 0 ? "I dag" : DAYS[new Date(key + "T12:00:00").getDay()]);

function header(w, m, big) {
  const top = w.addStack();
  top.layoutVertically();
  txt(top, PLACE + (m.stale ? " ·" : ""), big ? 15 : 13, "semibold");
  txt(top, r0(m.temp), big ? 44 : 38, "light");
}

function footerLines(w, m, small) {
  const line = w.addStack();
  line.layoutVertically();
  const row = line.addStack();
  row.centerAlignContent();
  sym(row, symbolName(m.cond, m.night), small ? 13 : 15);
  row.addSpacer(4);
  txt(row, TEXT[m.cond] || m.cond, small ? 12 : 13, "medium");
  txt(line, m.outlookShort && small ? m.outlookShort : `H:${r0(m.hi)}  L:${r0(m.lo)}`, small ? 12 : 13, "medium", m.outlookShort && small ? WHITE : DIM);
}

function hourRow(w, m) {
  const row = w.addStack();
  for (const [i, h] of m.hours.entries()) {
    const col = row.addStack();
    col.layoutVertically();
    col.centerAlignContent();
    const a = col.addStack(); a.addSpacer(); txt(a, i === 0 ? "Nu" : hourLabel(h.t), 11, "medium", DIM); a.addSpacer();
    col.addSpacer(3);
    const b = col.addStack(); b.addSpacer(); sym(b, symbolName(h.cond, m.night && i === 0), 15); b.addSpacer();
    col.addSpacer(3);
    const c = col.addStack(); c.addSpacer(); txt(c, r0(h.temp), 13, "medium"); c.addSpacer();
    if (i < m.hours.length - 1) row.addSpacer();
  }
}

function dayRows(w, m) {
  const all = m.days.flatMap((d) => [d.lo, d.hi]).filter((v) => v != null);
  const min = Math.min(...all), max = Math.max(...all), span = Math.max(1, max - min);
  for (const [i, d] of m.days.entries()) {
    const row = w.addStack();
    row.centerAlignContent();
    const l = row.addStack(); l.size = new Size(sz(44), 0); txt(l, dayLabel(d.key, i), 13, "medium");
    const s = row.addStack(); s.size = new Size(sz(28), 0); sym(s, symbolName(d.cond, false), 14);
    const p = row.addStack(); p.size = new Size(sz(34), 0);
    if ((d.pop || 0) >= 30) txt(p, Math.round(d.pop) + "%", 11, "semibold", new Color("#8fd0ff"));
    const lo = row.addStack(); lo.size = new Size(sz(30), 0); lo.addSpacer(); txt(lo, r0(d.lo), 13, "medium", DIM);
    row.addSpacer(6);
    // temperature bar
    const W = S > 1 ? 70 : 90;
    const bar = row.addStack(); bar.size = new Size(W, 4); bar.cornerRadius = 2; bar.backgroundColor = new Color("#ffffff", 0.2);
    if (d.lo != null && d.hi != null) {
      const x0 = ((d.lo - min) / span) * W, x1 = ((d.hi - min) / span) * W;
      bar.addSpacer(x0);
      const fill = bar.addStack(); fill.size = new Size(Math.max(4, x1 - x0), 4); fill.cornerRadius = 2;
      const g = new LinearGradient(); g.colors = [new Color("#7ed3f7"), new Color("#f8c95a")]; g.locations = [0, 1];
      g.startPoint = new Point(0, 0.5); g.endPoint = new Point(1, 0.5); fill.backgroundGradient = g;
    }
    bar.addSpacer();
    row.addSpacer(6);
    const hi = row.addStack(); hi.size = new Size(sz(30), 0); txt(hi, r0(d.hi), 13, "medium"); hi.addSpacer();
    if (i < m.days.length - 1) w.addSpacer(4);
  }
}

// ── Widgets ─────────────────────────────────────────────────────────────
function base(m) {
  const w = new ListWidget();
  const g = new LinearGradient();
  g.colors = [new Color(m.sky[0]), new Color(m.sky[1])];
  g.locations = [0, 1];
  w.backgroundGradient = g;
  w.url = BASE;
  w.refreshAfterDate = new Date(Date.now() + 10 * 60e3);
  return w;
}

function small(m) {
  const w = base(m);
  w.setPadding(14, 14, 14, 14);
  header(w, m, false);
  w.addSpacer();
  footerLines(w, m, true);
  return w;
}

function medium(m) {
  const w = base(m);
  w.setPadding(14, 16, 14, 16);
  const top = w.addStack();
  header(top, m, false);
  top.addSpacer();
  const right = top.addStack();
  right.layoutVertically();
  const a = right.addStack(); a.addSpacer(); sym(a, symbolName(m.cond, m.night), 18);
  const b = right.addStack(); b.addSpacer(); txt(b, TEXT[m.cond] || m.cond, 13, "medium");
  const c = right.addStack(); c.addSpacer(); txt(c, `H:${r0(m.hi)}  L:${r0(m.lo)}`, 13, "medium", DIM);
  w.addSpacer();
  if (m.outlookLong) { txt(w, "☂︎ " + m.outlookLong, 12, "semibold"); w.addSpacer(6); }
  hourRow(w, m);
  return w;
}

function large(m) {
  const w = medium(m);
  w.addSpacer(10);
  const line = w.addStack(); line.size = new Size(0, 0.5); line.backgroundColor = new Color("#ffffff", 0.3);
  line.addSpacer();
  w.addSpacer(10);
  dayRows(w, m);
  w.addSpacer();
  return w;
}

function lockRect(m) {
  const w = new ListWidget();
  w.url = BASE;
  const row = w.addStack(); row.centerAlignContent();
  sym(row, symbolName(m.cond, m.night), 14);
  row.addSpacer(4);
  txt(row, `${r0(m.temp)} ${TEXT[m.cond] || ""}`, 14, "semibold");
  txt(w, m.outlookShort || `H:${r0(m.hi)}  L:${r0(m.lo)}`, 13, "medium");
  txt(w, `Føles som ${r0(m.feels)}`, 12);
  return w;
}

function lockCircle(m) {
  const w = new ListWidget();
  w.url = BASE;
  w.addAccessoryWidgetBackground = true;
  const a = w.addStack(); a.addSpacer(); sym(a, symbolName(m.cond, m.night), 14); a.addSpacer();
  const b = w.addStack(); b.addSpacer(); txt(b, r0(m.temp), 16, "semibold"); b.addSpacer();
  return w;
}

function lockInline(m) {
  const w = new ListWidget();
  w.url = BASE;
  const row = w.addStack();
  sym(row, symbolName(m.cond, m.night), 12);
  txt(row, ` ${r0(m.temp)} ${m.outlookShort || TEXT[m.cond] || ""}`, 12);
  return w;
}

function errorWidget(e) {
  const w = new ListWidget();
  w.backgroundColor = new Color("#2c64a8");
  w.url = BASE;
  txt(w, PLACE, 13, "semibold");
  w.addSpacer(4);
  txt(w, "Ingen forbindelse", 12, "medium", DIM);
  console.error(e);
  w.refreshAfterDate = new Date(Date.now() + 5 * 60e3);
  return w;
}

// ── Main ────────────────────────────────────────────────────────────────
let widget;
const fam = config.widgetFamily || "large"; // in-app preview: large
if (!fam.startsWith("accessory")) S = SCALE;
try {
  const m = model(await load());
  widget = { small, medium, large, extraLarge: large, accessoryRectangular: lockRect, accessoryCircular: lockCircle, accessoryInline: lockInline }[fam](m);
} catch (e) {
  widget = errorWidget(e);
}

if (config.runsInWidget || config.runsInAccessoryWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentLarge();
}
Script.complete();
