"""NOAA CO-OPS client: tide predictions + tidal current predictions.

Both products are station-based, not gridded — the caller gets data from the
nearest prediction station plus that station's identity and distance, so the
scoring engine can flag station-direct vs. distant values (SPEC §6 caveat).
Station metadata is fetched once per process and cached in-module.
"""
import math
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.geo import haversine_nm

DATA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"

APP_NAME = "sailready.ai"
STATION_CACHE_TTL_S = 24 * 3600
MAX_STATION_DISTANCE_NM = 60.0

_station_cache: dict[str, tuple[float, list[dict]]] = {}


async def _get_stations(station_type: str) -> list[dict]:
    """station_type: 'tidepredictions' or 'currentpredictions'."""
    cached = _station_cache.get(station_type)
    if cached and time.monotonic() - cached[0] < STATION_CACHE_TTL_S:
        return cached[1]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(STATIONS_URL, params={"type": station_type})
        resp.raise_for_status()
    stations = resp.json().get("stations", [])
    _station_cache[station_type] = (time.monotonic(), stations)
    return stations


async def nearest_station(lat: float, lon: float, station_type: str) -> dict | None:
    """Returns {id, name, lat, lon, distance_nm} or None if nothing within range."""
    stations = await _get_stations(station_type)
    best: dict | None = None
    best_dist = MAX_STATION_DISTANCE_NM
    for s in stations:
        s_lat, s_lon = s.get("lat"), s.get("lng")
        if s_lat is None or s_lon is None:
            continue
        d = haversine_nm(lat, lon, s_lat, s_lon)
        if d < best_dist:
            best_dist = d
            best = {
                "id": s["id"],
                "name": s.get("name"),
                "lat": s_lat,
                "lon": s_lon,
                "distance_nm": round(d, 1),
            }
    return best


def _coops_params(product: str, station_id: str, start: datetime, end: datetime) -> dict:
    return {
        "product": product,
        "application": APP_NAME,
        "station": station_id,
        "begin_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "time_zone": "gmt",
        "units": "english",
        "interval": "h",
        "format": "json",
    }


def _parse_time(t: str) -> datetime:
    return datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


async def fetch_tides(
    station: dict, start: datetime, end: datetime
) -> dict[datetime, dict]:
    params = _coops_params("predictions", station["id"], start, end)
    params["datum"] = "MLLW"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(DATA_URL, params=params)
        resp.raise_for_status()
    payload = resp.json()
    out: dict[datetime, dict] = {}
    for p in payload.get("predictions", []):
        out[_parse_time(p["t"])] = {"tide_height_ft": float(p["v"])}
    return out


async def fetch_currents(
    station: dict, start: datetime, end: datetime
) -> dict[datetime, dict]:
    """Hourly current predictions.

    Harmonic stations honor interval=h and return hourly values. Subordinate
    stations (e.g. ACT*) ignore it and return only max-flood/slack/max-ebb
    events — for those we interpolate hourly values with a cosine curve
    between events (the standard approximation for reversing tidal currents),
    flagged current_is_interpolated so score drivers can disclose it.
    Fetch is padded ±1 day so the window's edge hours have bracketing events.
    """
    params = _coops_params(
        "currents_predictions",
        station["id"],
        start - timedelta(days=1),
        end + timedelta(days=1),
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(DATA_URL, params=params)
        resp.raise_for_status()
    payload = resp.json()
    cp = (payload.get("current_predictions") or {}).get("cp") or []

    events: list[tuple[datetime, float, float | None, float | None]] = []
    for p in cp:
        velocity = p.get("Velocity_Major")
        if velocity is None:
            continue
        events.append(
            (_parse_time(p["Time"]), velocity, p.get("meanFloodDir"), p.get("meanEbbDir"))
        )
    if not events:
        return {}
    events.sort(key=lambda e: e[0])

    def record(velocity: float, flood: float | None, ebb: float | None, interpolated: bool) -> dict:
        # Velocity_Major is signed along the flood/ebb axis
        return {
            "current_speed_kts": round(abs(velocity), 2),
            "current_dir_deg": flood if velocity >= 0 else ebb,
            "current_is_interpolated": interpolated,
        }

    on_the_hour = [e for e in events if e[0].minute == 0]
    if len(on_the_hour) >= 0.8 * len(events):
        # Harmonic station: hourly series came back directly
        return {t: record(v, f, e, False) for t, v, f, e in events}

    # Subordinate station: cosine-interpolate between events at each hour
    out: dict[datetime, dict] = {}
    t = start.replace(minute=0, second=0, microsecond=0)
    while t <= end:
        for (t1, v1, f1, e1), (t2, v2, _f2, _e2) in zip(events, events[1:]):
            if t1 <= t <= t2:
                frac = (t - t1).total_seconds() / (t2 - t1).total_seconds()
                v = v1 + (v2 - v1) * (1 - math.cos(math.pi * frac)) / 2
                out[t] = record(v, f1, e1, True)
                break
        t += timedelta(hours=1)
    return out
