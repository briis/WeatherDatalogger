// Types for the WeatherDatalogger API (weatherdatalogger/api/api_server.py).
// Field names mirror the database columns 1:1 — see
// weatherdatalogger/database/README.md for units and sources. Every field is
// nullable: a NULL means that role's station isn't registered (or hasn't
// reported yet), and the UI must render a placeholder rather than 0.

type N = number | null;
type S = string | null;

/** Single-row `combined_realtime` view — current station observations. */
export interface CombinedRealtime {
  recorded_at: S;
  data_recorded_at: S;
  air_quality_recorded_at: S;
  // Wind
  wind_lull_ms: N;
  wind_avg_ms: N;
  wind_gust_ms: N;
  wind_direction_deg: N;
  wind_beaufort: N;
  wind_beaufort_description: S;
  // Pressure
  station_pressure_mb: N;
  sea_level_pressure_mb: N;
  pressure_trend_mb: N;
  pressure_trend: S;
  sea_level_pressure_trend_mb: N;
  sea_level_pressure_trend: S;
  // Temperature & humidity
  air_temperature_c: N;
  relative_humidity_pct: N;
  dew_point_c: N;
  wet_bulb_c: N;
  delta_t_c: N;
  feels_like_c: N;
  heat_index_c: N;
  wind_chill_c: N;
  // Solar
  illuminance_lux: N;
  uv_index: N;
  solar_radiation_wm2: N;
  // Rain
  rain_accumulation_mm: N;
  rain_rate_mmh: N;
  // Lightning
  lightning_last_detected: S;
  lightning_count_3h: N;
  lightning_min_dist_3h_km: N;
  lightning_max_dist_3h_km: N;
  // Air properties / device
  vapor_pressure_mb: N;
  air_density_kgm3: N;
  battery_volts: N;
  battery_low: N;
  indoor_temperature_c: N;
  indoor_humidity_pct: N;
  // Air quality
  pm_1_ugm3: N;
  pm_2p5_ugm3: N;
  pm_2p5_1h_ugm3: N;
  pm_2p5_3h_ugm3: N;
  pm_2p5_24h_ugm3: N;
  pm_2p5_nowcast_ugm3: N;
  pm_10_ugm3: N;
  pm_10_1h_ugm3: N;
  pm_10_3h_ugm3: N;
  pm_10_24h_ugm3: N;
  pm_10_nowcast_ugm3: N;
  aqi_pm2p5: N;
  aqi_pm10: N;
  caqi_pm2p5: N;
  caqi_pm10: N;
}

/** Single-row `combined_realtime_stats` view. */
export interface CombinedRealtimeStats {
  wind_gust_high_today: N;
  wind_bearing_avg_day: N;
  wind_bearing_avg_10min: N;
  rain_total_yesterday: N;
  air_temp_high_today: N;
  air_temp_low_today: N;
  wind_speed_avg_10min: N;
}

/** GET /api/v1/current and every WS /api/v1/ws/current message. */
export interface CurrentSnapshot {
  version: number;
  updated_at: string;
  combined_realtime: CombinedRealtime | null;
  combined_realtime_stats: CombinedRealtimeStats | null;
}

/** HA-style condition strings written by the forecast dataloggers. */
export type WeatherCondition =
  | 'clear-night'
  | 'cloudy'
  | 'exceptional'
  | 'fog'
  | 'hail'
  | 'lightning'
  | 'lightning-rainy'
  | 'partlycloudy'
  | 'pouring'
  | 'rainy'
  | 'snowy'
  | 'snowy-rainy'
  | 'sunny'
  | 'windy'
  | 'windy-variant';

interface ForecastCommon {
  fetched_at: string;
  weather_condition: WeatherCondition | null;
  feels_like_c: N;
  humidity_pct: N;
  dew_point_c: N;
  wind_speed_ms: N;
  wind_gust_ms: N;
  wind_bearing_deg: N;
  pressure_mb: N;
  cloud_cover_pct: N;
  uv_index: N;
  solar_radiation_wm2: N;
  solar_energy_mjm2: N;
  snow_cm: N;
  snow_depth_cm: N;
  precipitation_type: S;
}

export interface ForecastCurrent extends ForecastCommon {
  temperature_c: N;
  temperature_high_c: N;
  temperature_low_c: N;
  visibility_km: N;
  sunrise: S;
  sunset: S;
  moon_phase: N;
  description: S;
}

export interface ForecastHour extends ForecastCommon {
  /** UTC hour, naive ISO string (no offset). */
  forecast_time: string;
  temperature_c: N;
  precipitation_mm: N;
  precipitation_probability_pct: N;
  visibility_km: N;
  severe_risk: N;
}

export interface ForecastDay extends ForecastCommon {
  /** Day as reported by the provider, naive ISO string. */
  forecast_time: string;
  temperature_high_c: N;
  temperature_low_c: N;
  precipitation_mm: N;
  precipitation_probability_pct: N;
  precipitation_cover_pct: N;
  severe_risk: N;
  sunrise: S;
  sunset: S;
  moon_phase: N;
  description: S;
}

/** GET /api/v1/forecast */
export interface Forecast {
  provider: string;
  location: string;
  current: ForecastCurrent | null;
  hourly: ForecastHour[];
  daily: ForecastDay[];
}

/** One `history_charting` row — only the requested fields are present. */
export type HistoryRow = { window_start: string } & Partial<
  Record<keyof CombinedRealtime, number | string | null>
>;

/** GET /api/v1/history */
export interface History {
  hours: number;
  fields: string[];
  rows: HistoryRow[];
}

/** One row of GET /api/v1/daily — a local calendar day. */
export interface DailySummary {
  day: string;
  air_temp_high_c: N;
  air_temp_low_c: N;
  air_temp_avg_c: N;
  relative_humidity_avg_pct: N;
  dew_point_avg_c: N;
  feels_like_low_c: N;
  feels_like_high_c: N;
  sea_level_pressure_avg_mb: N;
  sea_level_pressure_low_mb: N;
  sea_level_pressure_high_mb: N;
  wind_avg_ms: N;
  wind_gust_max_ms: N;
  rain_total_mm: N;
  rain_rate_max_mmh: N;
  uv_index_max: N;
  solar_radiation_max_wm2: N;
  caqi_pm2p5_max: N;
  aqi_pm2p5_max: N;
  samples: number;
}

export interface Daily {
  days: number;
  timezone: string;
  rows: DailySummary[];
}
