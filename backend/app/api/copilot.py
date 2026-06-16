"""Co-pilot endpoints backed by the Temporal workflow (POC branch).

Position updates become signals; the live co-pilot state is a workflow query.
All no-op gracefully when TEMPORAL_ENABLED is false so the rest of the app is
unaffected on the main deployment.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.trips import get_owned_trip
from app.auth import CurrentUser, get_current_user
from app.config import settings
from app.db import get_db
from app.schemas import Envelope

router = APIRouter(prefix="/trips", tags=["copilot"])


class PositionIn(BaseModel):
    lat: float
    lon: float


def _require_temporal() -> None:
    if not settings.temporal_enabled:
        raise HTTPException(status_code=503, detail="temporal orchestration not enabled")


@router.post("/{trip_id}/position", response_model=Envelope[dict])
async def push_position(
    trip_id: uuid.UUID,
    payload: PositionIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _require_temporal()
    await get_owned_trip(trip_id, db)  # ownership + 404 via RLS
    from app.temporal.client import signal_position

    await signal_position(str(trip_id), payload.lat, payload.lon)
    return Envelope[dict](data={"accepted": True})


@router.get("/{trip_id}/copilot", response_model=Envelope[dict])
async def get_copilot(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _require_temporal()
    await get_owned_trip(trip_id, db)
    from app.temporal.client import query_state

    state = await query_state(str(trip_id))
    if state is None:
        raise HTTPException(status_code=404, detail="no active watch for this trip")
    return Envelope[dict](data=state)
