import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.charts.depth import charted_depth_at
from app.charts.tiles import get_tile
from app.db import get_db
from app.schemas import Envelope

router = APIRouter(prefix="/charts", tags=["charts"])


@router.get("/depth", response_model=Envelope[dict])
async def get_depth(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    return Envelope[dict](data=await charted_depth_at(db, lat, lon))


# No auth: <img> tile requests can't carry Authorization headers, and this is
# a cache of public-domain NOAA chart renders.
@router.get("/enc-tile/{z}/{x}/{y}.png")
async def enc_tile(
    z: int,
    x: int,
    y: int,
    db: AsyncSession = Depends(get_db),
):
    if not (3 <= z <= 18):
        raise HTTPException(status_code=404, detail="zoom out of range")
    try:
        png = await get_tile(db, z, x, y)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NOAA chart service: {exc}")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
