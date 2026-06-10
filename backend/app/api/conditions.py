from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.conditions.service import get_hourly_conditions
from app.db import get_db
from app.schemas import Envelope

router = APIRouter(prefix="/conditions", tags=["conditions"])

MAX_WINDOW = timedelta(days=8)


@router.get("", response_model=Envelope[dict])
async def get_conditions(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    time_from: datetime = Query(alias="from"),
    time_to: datetime = Query(alias="to"),
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    if time_from.tzinfo is None or time_to.tzinfo is None:
        raise HTTPException(status_code=422, detail="from/to must include a timezone offset")
    if time_to <= time_from:
        raise HTTPException(status_code=422, detail="to must be after from")
    if time_to - time_from > MAX_WINDOW:
        raise HTTPException(status_code=422, detail="window cannot exceed 8 days")

    data = await get_hourly_conditions(db, lat, lon, time_from, time_to)
    return Envelope[dict](data=data)
