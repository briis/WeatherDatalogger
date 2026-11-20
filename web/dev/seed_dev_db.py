#!/usr/bin/env python3
"""
Seed a *development* WeatherDatalogger database with plausible fake data.

Fills stations/realtime/history_charting and the openmeteo forecast_* tables
so the API (and through it the web frontend) can be developed without access
to the production database. Never run this against production — it deletes
and rewrites rows.

Usage:
    python3 seed_dev_db.py --host localhost --user root --password '' [--days 30]
"""

import argparse
import math
import random
from datetime import UTC, datetime, timedelta

import pymysql

DAVIS, TEMPEST, AIRLINK = "davis-dev", "ST-DEV00001", "airlink-dev"
WMO_CONDITIONS = [
    ("sunny", "Klart"),
    ("partlycloudy", "Delvis skyet"),
    ("cloudy", "Overskyet"),
    ("rainy", "Let regn"),
    ("snowy", "Let sne"),
    ("clear-night", "Klart"),
]


def temp_at(t: datetime) -> float:
    """Return a November-ish diurnal temperature curve for Roskilde."""
    hour = t.hour + t.minute / 60
    day_wave = 2.5 * math.sin((hour - 9) / 24 * 2 * math.pi)
    trend = 1.5 * math.sin(t.timetuple().tm_yday / 5)
    return round(2.0 + day_wave + trend + random.uniform(-0.3, 0.3), 1)


def seed(conn: pymysql.connections.Connection, days: int) -> None:
    """Rewrite the dev tables with generated data."""
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    cur = conn.cursor()
    for table in (
        "realtime",
        "history_charting",
        "forecast_current",
        "forecast_hourly",
        "forecast_daily",
    ):
        cur.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table names
    for sid, stype in ((DAVIS, "davis"), (TEMPEST, "tempest"), (AIRLINK, "airlink")):
        cur.execute(
            "INSERT IGNORE INTO stations (station_id, station_type) VALUES (%s, %s)",
            (sid, stype),
        )

    t_now = temp_at(now)
    cur.execute(
        "INSERT INTO realtime (station_id, recorded_at, wind_lull_ms, wind_avg_ms,"
        " wind_gust_ms, wind_direction_deg, wind_beaufort, wind_beaufort_description,"
        " air_temperature_c, relative_humidity_pct, dew_point_c, feels_like_c,"
        " wind_chill_c, rain_accumulation_mm, rain_rate_mmh, battery_low,"
        " indoor_temperature_c, indoor_humidity_pct, vapor_pressure_mb)"
        " VALUES (%s,%s,1.2,3.1,7.0,296,2,'Svag vind',%s,78,%s,%s,%s,0.4,0,0,21.5,44,6.1)",
        (DAVIS, now, t_now, round(t_now - 3.4, 1), t_now - 1, t_now - 1),
    )
    cur.execute(
        "INSERT INTO realtime (station_id, recorded_at, station_pressure_mb,"
        " sea_level_pressure_mb, pressure_trend_mb, pressure_trend,"
        " sea_level_pressure_trend_mb, sea_level_pressure_trend, wet_bulb_c,"
        " delta_t_c, illuminance_lux, uv_index, solar_radiation_wm2,"
        " lightning_last_detected, lightning_count_3h, lightning_min_dist_3h_km,"
        " lightning_max_dist_3h_km, air_density_kgm3, battery_volts)"
        " VALUES (%s,%s,991.2,997.4,-1.4,'Falling',-1.4,'Falling',%s,1.2,"
        " 18500,0.3,140,%s,0,NULL,NULL,1.281,2.68)",
        (TEMPEST, now, round(t_now - 1.2, 1), now - timedelta(days=12)),
    )
    cur.execute(
        "INSERT INTO realtime (station_id, recorded_at, pm_1_ugm3, pm_2p5_ugm3,"
        " pm_2p5_1h_ugm3, pm_2p5_24h_ugm3, pm_2p5_nowcast_ugm3, pm_10_ugm3,"
        " pm_10_nowcast_ugm3, aqi_pm2p5, aqi_pm10, caqi_pm2p5, caqi_pm10)"
        " VALUES (%s,%s,3.1,5.4,5.9,6.8,5.7,8.2,8.5,24,8,9,8)",
        (AIRLINK, now),
    )

    # history_charting — one row per 10-minute window
    start = (now - timedelta(days=days)).replace(second=0)
    start -= timedelta(minutes=start.minute % 10)
    rows = []
    t = start
    rain_today = 0.0
    while t <= now:
        if t.hour == 23 and t.minute == 0:  # ~local midnight (UTC+1)
            rain_today = 0.0
        if random.random() < 0.04:
            rain_today += round(random.uniform(0.1, 0.6), 1)
        temp = temp_at(t)
        wind = max(0.0, 3 + 2 * math.sin(t.timestamp() / 20000) + random.uniform(-1, 1))
        rows.append(
            (
                t,
                round(wind, 1),
                round(max(0, wind - 1.5), 1),
                round(wind + random.uniform(1, 4), 1),
                int(250 + 60 * math.sin(t.timestamp() / 50000)) % 360,
                temp,
                round(80 + 10 * math.sin(t.timestamp() / 30000), 1),
                round(temp - 3, 1),
                round(temp - 1.5, 1),
                round(1000 + 8 * math.sin(t.timestamp() / 200000), 1),
                round(max(0, 2 * math.sin((t.hour - 6) / 12 * math.pi)), 1),
                round(max(0, 250 * math.sin((t.hour - 7) / 9 * math.pi)), 0),
                rain_today,
                round(random.uniform(0, 2), 1) if rain_today else 0,
                random.randint(5, 15),
            )
        )
        t += timedelta(minutes=10)
    cur.executemany(
        "INSERT INTO history_charting (window_start, wind_avg_ms, wind_lull_ms,"
        " wind_gust_ms, wind_direction_deg, air_temperature_c, relative_humidity_pct,"
        " dew_point_c, feels_like_c, sea_level_pressure_mb, uv_index,"
        " solar_radiation_wm2, rain_accumulation_mm, rain_rate_mmh, caqi_pm2p5)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        rows,
    )

    # Forecast — openmeteo/home
    day0 = now.replace(hour=0, minute=0, second=0)
    cur.execute(
        "INSERT INTO forecast_current (provider, location, fetched_at,"
        " weather_condition, temperature_c, temperature_high_c, temperature_low_c,"
        " feels_like_c, humidity_pct, dew_point_c, wind_speed_ms, wind_gust_ms,"
        " wind_bearing_deg, pressure_mb, cloud_cover_pct, uv_index, visibility_km,"
        " sunrise, sunset, description)"
        " VALUES ('openmeteo','home',%s,'sunny',%s,4,0,3,78,0,3,7,296,997,20,0,33,"
        " '07:58:00','15:56:00','Mainly clear')",
        (now, t_now),
    )
    hourly = []
    for h in range(-1, 48):
        ft = now.replace(minute=0, second=0) + timedelta(hours=h)
        cond = WMO_CONDITIONS[5 if ft.hour >= 15 or ft.hour < 7 else h % 3][0]
        hourly.append(
            (
                ft,
                now,
                cond,
                temp_at(ft),
                temp_at(ft) - 1.5,
                80,
                round(3 + random.uniform(-1, 2), 1),
                round(6 + random.uniform(-1, 3), 1),
                290,
                998,
                random.randint(10, 90),
                0,
                round(random.choice([0, 0, 0, 0.2, 0.5]), 1),
                random.choice([0, 5, 10, 30, 50]),
                30,
            )
        )
    cur.executemany(
        "INSERT INTO forecast_hourly (provider, location, forecast_time, fetched_at,"
        " weather_condition, temperature_c, feels_like_c, humidity_pct,"
        " wind_speed_ms, wind_gust_ms, wind_bearing_deg, pressure_mb,"
        " cloud_cover_pct, uv_index, precipitation_mm,"
        " precipitation_probability_pct, visibility_km)"
        " VALUES ('openmeteo','home',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        hourly,
    )
    daily = []
    highs = [4, 6, 4, 3, 3, 2, 2, 4, 4, 3, 5, 4, 3, 2]
    for d in range(14):
        cond = [
            "sunny",
            "sunny",
            "cloudy",
            "cloudy",
            "partlycloudy",
            "partlycloudy",
            "sunny",
            "rainy",
            "partlycloudy",
            "partlycloudy",
            "cloudy",
            "rainy",
            "snowy",
            "sunny",
        ][d]
        daily.append(
            (
                day0 + timedelta(days=d),
                now,
                cond,
                highs[d],
                highs[d] - random.randint(3, 6),
                round(random.uniform(2, 6), 1),
                round(random.uniform(6, 12), 1),
                290,
                round(random.choice([0, 0, 0.5, 1.2, 3.4]), 1),
                50 if cond in ("rainy", "snowy") else random.randint(0, 20),
                round(max(0.2, 0.9 - d * 0.03), 1),
                "07:58:00",
                "15:56:00",
            )
        )
    cur.executemany(
        "INSERT INTO forecast_daily (provider, location, forecast_time, fetched_at,"
        " weather_condition, temperature_high_c, temperature_low_c, wind_speed_ms,"
        " wind_gust_ms, wind_bearing_deg, precipitation_mm,"
        " precipitation_probability_pct, uv_index, sunrise, sunset)"
        " VALUES ('openmeteo','home',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        daily,
    )
    conn.commit()


def main() -> None:
    """Parse arguments and seed."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=3306)
    p.add_argument("--user", default="root")
    p.add_argument("--password", default="")
    p.add_argument("--database", default="weatherdatalogger")
    p.add_argument("--days", type=int, default=30)
    a = p.parse_args()
    conn = pymysql.connect(
        host=a.host, port=a.port, user=a.user, password=a.password, database=a.database
    )
    seed(conn, a.days)


if __name__ == "__main__":
    main()
