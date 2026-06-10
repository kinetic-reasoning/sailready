"""NOAA ENC tile proxy with PostGIS-backed cache.

First request for a tile renders live on NOAA's Maritime Chart Service
(slow); every subsequent request serves from the local cache (fast). Charts
update on a weekly cycle -> 7 day TTL.
"""
import math
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MCS_EXPORT = (
    "https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/ENCOnline/"
    "MapServer/exts/MaritimeChartService/MapServer/export"
)
TILE_TTL = timedelta(days=7)


def tile_bbox_4326(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Slippy-map tile -> (west, south, east, north) in EPSG:4326."""
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


async def fetch_tile_from_noaa(z: int, x: int, y: int) -> bytes:
    west, south, east, north = tile_bbox_4326(z, x, y)
    params = {
        "bbox": f"{west},{south},{east},{north}",
        "bboxSR": "4326",
        "imageSR": "3857",
        "size": "256,256",
        "format": "png32",
        "transparent": "true",
        "f": "image",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(MCS_EXPORT, params=params)
        resp.raise_for_status()
    return resp.content


async def get_tile(db: AsyncSession, z: int, x: int, y: int) -> bytes:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            text("SELECT png, fetched_at FROM enc_tile_cache WHERE z=:z AND x=:x AND y=:y"),
            {"z": z, "x": x, "y": y},
        )
    ).one_or_none()
    if row is not None and now - row.fetched_at < TILE_TTL:
        return bytes(row.png)

    png = await fetch_tile_from_noaa(z, x, y)
    await db.execute(
        text(
            "INSERT INTO enc_tile_cache (z, x, y, png, fetched_at) "
            "VALUES (:z, :x, :y, :png, :now) "
            "ON CONFLICT (z, x, y) DO UPDATE SET png = :png, fetched_at = :now"
        ),
        {"z": z, "x": x, "y": y, "png": png, "now": now},
    )
    return png
