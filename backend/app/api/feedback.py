import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.trips import get_owned_trip
from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import TripFeedback
from app.schemas import Envelope, TripFeedbackIn, TripFeedbackOut

router = APIRouter(prefix="/trips/{trip_id}/feedback", tags=["feedback"])


@router.post("", response_model=Envelope[TripFeedbackOut], status_code=201)
async def submit_feedback(
    trip_id: uuid.UUID,
    payload: TripFeedbackIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    await get_owned_trip(trip_id, db)  # 404 if not visible
    feedback = TripFeedback(
        trip_id=trip_id,
        user_id=current.id,
        **payload.model_dump(exclude={"actual_leg_times"}),
        actual_leg_times=[
            lt.model_dump(mode="json") for lt in payload.actual_leg_times
        ],
    )
    db.add(feedback)
    await db.flush()
    await db.refresh(feedback)
    return Envelope[TripFeedbackOut](data=TripFeedbackOut.model_validate(feedback))


@router.get("", response_model=Envelope[list[TripFeedbackOut]])
async def list_feedback(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    await get_owned_trip(trip_id, db)
    items = (
        (
            await db.execute(
                select(TripFeedback)
                .where(TripFeedback.trip_id == trip_id)
                .order_by(TripFeedback.submitted_at)
            )
        )
        .scalars()
        .all()
    )
    return Envelope[list[TripFeedbackOut]](
        data=[TripFeedbackOut.model_validate(f) for f in items]
    )
