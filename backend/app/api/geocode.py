"""Place search for marinas/anchorages — proxied through Nominatim (OSM).

Proxied server-side (not called from the browser) so we present a proper
User-Agent per Nominatim's usage policy and can swap providers later without
touching clients.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.schemas import Envelope

router = APIRouter(prefix="/geocode", tags=["geocode"])

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "sailready.ai (ken.e.holden@gmail.com)"}


@router.get("", response_model=Envelope[list[dict]])
async def search_places(
    q: str = Query(min_length=3, max_length=120),
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    params = {"q": q, "format": "jsonv2", "limit": 6, "countrycodes": "us"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=HEADERS)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"geocoder unavailable: {exc}")
    results = [
        {
            "name": r.get("display_name"),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "kind": r.get("type"),
        }
        for r in resp.json()
    ]
    return Envelope[list[dict]](data=results)
