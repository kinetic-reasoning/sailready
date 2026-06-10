"""Open-Meteo clients: wind (forecast API) and waves (marine API).

Marine-model caveat (see SPEC §6): the wave model is a global swell model and
under-resolves fetch-limited chop inside Tampa Bay. Values are stored as
returned; the scoring engine treats in-bay wave data regime-aware.
"""
from datetime import datetime, timedelta, timezone

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

M_TO_FT = 3.28084


def _parse_hours(payload: dict, fields: dict[str, str]) -> dict[datetime, dict]:
    """Zip Open-Meteo's parallel hourly arrays into {utc_hour: {our_name: value}}."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    out: dict[datetime, dict] = {}
    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        record = {}
        for api_name, our_name in fields.items():
            values = hourly.get(api_name) or []
            record[our_name] = values[i] if i < len(values) else None
        out[dt] = record
    return out


async def fetch_wind(lat: float, lon: float, start: datetime, end: datetime) -> dict[datetime, dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": (
            "wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
            "precipitation_probability,precipitation,weather_code"
        ),
        "wind_speed_unit": "kn",
        "timezone": "UTC",
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(FORECAST_URL, params=params)
        resp.raise_for_status()
    hours = _parse_hours(
        resp.json(),
        {
            "wind_speed_10m": "wind_speed_kts",
            "wind_gusts_10m": "wind_gust_kts",
            "wind_direction_10m": "wind_dir_deg",
            "precipitation_probability": "rain_prob_pct",
            "precipitation": "rain_mm_hr",
            "weather_code": "weather_code",
        },
    )
    # Open-Meteo semantics: wind_gusts_10m at hour T is the max gust of the
    # PRECEDING hour, while wind_speed_10m is the mean AT hour T. On building
    # wind this makes raw "gusts" trail below sustained speed. Re-align each
    # hour's gust to the value reported at T+1 (the max DURING this hour) and
    # floor at sustained speed — a gust is by definition >= the mean.
    raw_gusts = {t: rec.get("wind_gust_kts") for t, rec in hours.items()}
    for t, rec in hours.items():
        gust = raw_gusts.get(t + timedelta(hours=1), raw_gusts.get(t))
        wind = rec.get("wind_speed_kts")
        if gust is not None and wind is not None and gust < wind:
            gust = wind
        rec["wind_gust_kts"] = gust
    return hours


async def fetch_waves(lat: float, lon: float, start: datetime, end: datetime) -> dict[datetime, dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period",
        "timezone": "UTC",
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(MARINE_URL, params=params)
        resp.raise_for_status()
    hours = _parse_hours(
        resp.json(),
        {
            "wave_height": "wave_height_ft",  # converted below
            "wave_direction": "wave_dir_deg",
            "wave_period": "wave_period_s",
        },
    )
    for record in hours.values():
        if record.get("wave_height_ft") is not None:
            record["wave_height_ft"] = round(record["wave_height_ft"] * M_TO_FT, 1)
    return hours
