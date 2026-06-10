from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.charts.depth import charted_depth_at
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
