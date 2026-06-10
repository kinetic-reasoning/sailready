"""Conditions orchestration: cache-first fetch and per-hour merge of all sources.

Every scoring run and API request goes through here — external APIs are hit
only when the Postgres cache misses or has expired (SPEC §8: the conditions
cache decouples scoring from API availability).
"""
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions import coops, nws, openmeteo
from app.geo import snap_coord
from app.models import ConditionsCache

# Forecasts change as models re-run; predictions (tide/current) are astronomical
# and stable — different TTLs.
TTL = {
    "open_meteo_wind": timedelta(hours=3),
    "open_meteo_marine": timedelta(hours=3),
    "coops_tides": timedelta(hours=24),
    "coops_currents": timedelta(hours=24),
}

FetchFn = Callable[[], Awaitable[dict[datetime, dict]]]


def hour_range(t_from: datetime, t_to: datetime) -> list[datetime]:
    start = t_from.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = t_to.astimezone(timezone.utc)
    hours = []
    t = start
    while t <= end:
        hours.append(t)
        t += timedelta(hours=1)
    return hours


async def _cached_source(
    db: AsyncSession,
    source: str,
    lat: float,
    lon: float,
    hours: list[datetime],
    fetch: FetchFn,
) -> dict[datetime, dict]:
    """Cache-first read of one source for one snapped point over a set of hours."""
    slat, slon = snap_coord(lat), snap_coord(lon)
    now = datetime.now(timezone.utc)

    rows = (
        await db.execute(
            select(ConditionsCache).where(
                ConditionsCache.source == source,
                ConditionsCache.lat == slat,
                ConditionsCache.lon == slon,
                ConditionsCache.valid_time.in_(hours),
                ConditionsCache.expires_at > now,
            )
        )
    ).scalars()
    cached = {row.valid_time: row.data for row in rows}

    if all(h in cached for h in hours):
        return cached

    fetched = await fetch()
    wanted = {h: v for h, v in fetched.items() if h in set(hours)}
    if wanted:
        expires = now + TTL[source]
        await db.execute(
            pg_insert(ConditionsCache)
            .values(
                [
                    {
                        "source": source,
                        "lat": slat,
                        "lon": slon,
                        "valid_time": h,
                        "expires_at": expires,
                        "data": v,
                    }
                    for h, v in wanted.items()
                ]
            )
            .on_conflict_do_update(
                index_elements=["source", "lat", "lon", "valid_time"],
                set_={
                    "data": pg_insert(ConditionsCache).excluded.data,
                    "fetched_at": now,
                    "expires_at": expires,
                },
            )
        )
    # Upstream may not cover the whole window (e.g. beyond forecast horizon) —
    # whatever is missing simply stays absent and merges as null.
    return {**cached, **wanted}


async def get_hourly_conditions(
    db: AsyncSession, lat: float, lon: float, t_from: datetime, t_to: datetime
) -> dict:
    """Merged hourly conditions at a point, plus station metadata and live alerts."""
    hours = hour_range(t_from, t_to)
    start, end = hours[0], hours[-1]

    tide_station = await coops.nearest_station(lat, lon, "tidepredictions")
    current_station = await coops.nearest_station(lat, lon, "currentpredictions")

    wind = await _cached_source(
        db, "open_meteo_wind", lat, lon, hours, lambda: openmeteo.fetch_wind(lat, lon, start, end)
    )
    waves = await _cached_source(
        db, "open_meteo_marine", lat, lon, hours, lambda: openmeteo.fetch_waves(lat, lon, start, end)
    )
    tides: dict[datetime, dict] = {}
    if tide_station is not None:
        tides = await _cached_source(
            db, "coops_tides", lat, lon, hours,
            lambda: coops.fetch_tides(tide_station, start, end),
        )
    currents: dict[datetime, dict] = {}
    if current_station is not None:
        currents = await _cached_source(
            db, "coops_currents", lat, lon, hours,
            lambda: coops.fetch_currents(current_station, start, end),
        )

    alerts = await nws.fetch_active_alerts(lat, lon)

    merged = []
    for h in hours:
        record: dict = {"valid_time": h.isoformat()}
        record.update(wind.get(h) or {})
        record.update(waves.get(h) or {})
        record.update(tides.get(h) or {})
        record.update(currents.get(h) or {})
        merged.append(record)

    return {
        "point": {"lat": lat, "lon": lon},
        "stations": {"tide": tide_station, "current": current_station},
        "hours": merged,
        "alerts": alerts,
    }
