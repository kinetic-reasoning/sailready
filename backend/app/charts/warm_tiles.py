"""Pre-warm the ENC tile cache for a bounding box — the local equivalent of a
chartplotter pre-loading chart chunks for your cruising area.

Usage:
    docker compose run --rm api python -m app.charts.warm_tiles \
        [west south east north] [min_zoom] [max_zoom]

Defaults: Tampa Bay to Anna Maria, zooms 10-14.
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.charts.tiles import fetch_tile_from_noaa

DEFAULT_BBOX = (-82.95, 27.45, -82.30, 28.05)  # Tampa Bay + Anna Maria
DEFAULT_ZOOMS = (10, 14)
CONCURRENCY = 4  # be polite to a free government server


def tiles_for_bbox(west, south, east, north, z):
    n = 2**z
    x_min = int((west + 180) / 360 * n)
    x_max = int((east + 180) / 360 * n)

    def lat_to_y(lat):
        rad = math.radians(lat)
        return int((1 - math.asinh(math.tan(rad)) / math.pi) / 2 * n)

    y_min, y_max = lat_to_y(north), lat_to_y(south)
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            yield z, x, y


async def main() -> None:
    args = [float(a) for a in sys.argv[1:]]
    bbox = tuple(args[0:4]) if len(args) >= 4 else DEFAULT_BBOX
    z_min = int(args[4]) if len(args) >= 5 else DEFAULT_ZOOMS[0]
    z_max = int(args[5]) if len(args) >= 6 else DEFAULT_ZOOMS[1]

    todo = [t for z in range(z_min, z_max + 1) for t in tiles_for_bbox(*bbox, z)]
    print(f"warming {len(todo)} tiles, z{z_min}-z{z_max}, bbox {bbox}")

    engine = create_async_engine(os.environ["DATABASE_URL_ADMIN"])
    semaphore = asyncio.Semaphore(CONCURRENCY)
    done = failed = skipped = 0

    async def warm(z, x, y):
        nonlocal done, failed, skipped
        async with semaphore:
            async with engine.connect() as conn:
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM enc_tile_cache WHERE z=:z AND x=:x AND y=:y"),
                        {"z": z, "x": x, "y": y},
                    )
                ).scalar()
                if exists:
                    skipped += 1
                    return
            try:
                png = await fetch_tile_from_noaa(z, x, y)
            except httpx.HTTPError:
                failed += 1
                return
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO enc_tile_cache (z, x, y, png, fetched_at) "
                        "VALUES (:z, :x, :y, :png, :now) ON CONFLICT (z, x, y) "
                        "DO UPDATE SET png = :png, fetched_at = :now"
                    ),
                    {"z": z, "x": x, "y": y, "png": png, "now": datetime.now(timezone.utc)},
                )
            done += 1
            if done % 50 == 0:
                print(f"  {done} fetched, {skipped} cached, {failed} failed")

    await asyncio.gather(*(warm(z, x, y) for z, x, y in todo))
    await engine.dispose()
    print(f"DONE: {done} fetched, {skipped} already cached, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
