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
    course_deg: float = 0.0
    cts_deg: float | None = None
    tack_headings: str | None = None
    boat_speed_kts: float = 0.0
    current_along_kts: float = 0.0
    wind_speed_kts: float | None = None
    wind_gust_kts: float | None = None
    wind_dir_deg: float | None = None
    wave_height_ft: float | None = None
    rain_prob_pct: float | None = None
    current_speed_kts: float | None = None
    current_dir_deg: float | None = None
    current_is_interpolated: bool = False
    wind_angle_deg: float | None = None
    point_of_sail: str | None = None
    leg_mode: str = "auto"


class ScoreOut(BaseModel):
    score: int
    feasible: bool
    outbound_arrival: datetime | None
    return_home: datetime | None
    turn_around_deadline: datetime | None
    max_reachable_distance_nm: float | None
    suggestions: list[dict]
    drivers: list[DriverOut]
    legs: list[LegOut]
    conditions_summary: dict


class ScoreHistoryOut(ScoreOut):
    forecast_date: str
    scored_at: datetime
    is_current: bool


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
        conditions_summary=result.conditions_summary,
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
            feasible=row.feasible,
            outbound_arrival=row.outbound_arrival,
            return_home=row.return_home,
            turn_around_deadline=row.turn_around_deadline,
            max_reachable_distance_nm=(
                float(row.max_reachable_distance_nm)
                if row.max_reachable_distance_nm is not None
                else None
            ),
            suggestions=row.suggestions,
            conditions_summary=row.conditions_summary,
            legs=[LegOut(**leg) for leg in row.legs],
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
