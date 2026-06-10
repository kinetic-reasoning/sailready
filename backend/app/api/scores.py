import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.trips import get_owned_trip
from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.engine.runner import rescore_trip
from app.engine.scoring import ScoreResult
from app.models import TripScore
from app.schemas import Envelope

router = APIRouter(prefix="/trips", tags=["scoring"])


class DriverOut(BaseModel):
    constraint_type: str
    severity: str
    leg: str | None
    waypoint_order: int | None
    actual_value: float | None
    threshold_value: float | None
    is_interpolated: bool
    description: str


class LegOut(BaseModel):
    leg: str
    from_order: int
    to_order: int
    start: datetime
    end: datetime
    distance_nm: float
    sog_kts: float
    mode: str


class ScoreOut(BaseModel):
    score: int
    feasible: bool
    outbound_arrival: datetime
    return_home: datetime
    turn_around_deadline: datetime | None
    max_reachable_distance_nm: float | None
    suggestions: list[dict]
    drivers: list[DriverOut]
    legs: list[LegOut]


class ScoreHistoryOut(BaseModel):
    forecast_date: str
    scored_at: datetime
    score: int
    is_current: bool
    turn_around_deadline: datetime | None
    suggestions: list[dict]
    drivers: list[DriverOut]


def score_out(result: ScoreResult) -> ScoreOut:
    return ScoreOut(
        score=result.score,
        feasible=result.feasible,
        outbound_arrival=result.outbound_arrival,
        return_home=result.return_home,
        turn_around_deadline=result.turn_around_deadline,
        max_reachable_distance_nm=result.max_reachable_distance_nm,
        suggestions=result.suggestions,
        drivers=[DriverOut(**vars(d)) for d in result.drivers],
        legs=[LegOut(**vars(leg)) for leg in result.legs],
    )


@router.post("/{trip_id}/score", response_model=Envelope[ScoreOut])
async def score_trip_now(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    trip = await get_owned_trip(trip_id, db)
    if trip.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"cannot score a {trip.status} trip")
    if not trip.waypoints:
        raise HTTPException(status_code=409, detail="add route waypoints before scoring")
    result = await rescore_trip(db, trip)
    return Envelope[ScoreOut](data=score_out(result))


@router.get("/{trip_id}/scores", response_model=Envelope[list[ScoreHistoryOut]])
async def score_history(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    await get_owned_trip(trip_id, db)
    rows = (
        (
            await db.execute(
                select(TripScore)
                .where(TripScore.trip_id == trip_id)
                .options(selectinload(TripScore.drivers))
                .order_by(TripScore.forecast_date.desc())
            )
        )
        .scalars()
        .all()
    )
    history = [
        ScoreHistoryOut(
            forecast_date=row.forecast_date.isoformat(),
            scored_at=row.scored_at,
            score=row.score,
            is_current=row.is_current,
            turn_around_deadline=row.turn_around_deadline,
            suggestions=row.suggestions,
            drivers=[
                DriverOut(
                    constraint_type=d.constraint_type,
                    severity=d.severity,
                    leg=d.leg,
                    waypoint_order=d.waypoint_order,
                    actual_value=float(d.actual_value) if d.actual_value is not None else None,
                    threshold_value=(
                        float(d.threshold_value) if d.threshold_value is not None else None
                    ),
                    is_interpolated=d.is_interpolated,
                    description=d.description,
                )
                for d in row.drivers
            ],
        )
        for row in rows
    ]
    return Envelope[list[ScoreHistoryOut]](data=history)
