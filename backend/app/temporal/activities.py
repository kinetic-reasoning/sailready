"""Temporal activities — the side-effecting work the workflow orchestrates.

Activities run in the worker process (not the workflow sandbox), so they may
do real I/O: hit NOAA/Open-Meteo, read the chart tables, write scores, send
mail. Each is a thin wrapper over code that already existed — Temporal adds
durable retries and timeouts around them, nothing more.

Idempotency: rescore upserts on (trip_id, forecast_date), so a retried or
duplicated activity overwrites rather than double-posting. That property is
what makes the automatic retries safe.
"""
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from temporalio import activity

from app.engine.runner import rescore_trip
from app.models import Notification, Trip

# One engine per worker process, created lazily — activities are long-lived.
_engine = None
_sessions = None


def _sessionmaker():
    global _engine, _sessions
    if _sessions is None:
        _engine = create_async_engine(os.environ["DATABASE_URL_ADMIN"])
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessions


@dataclass
class RescoreResult:
    """Small, JSON-safe summary returned to the workflow. We deliberately do
    NOT return the full driver/leg detail — keeping activity results tiny keeps
    the workflow's event history small and fast to replay."""

    trip_id: str
    found: bool
    score: int | None = None
    feasible: bool | None = None
    turn_around_deadline: str | None = None
    status: str | None = None


async def _load_trip(db, trip_id: str) -> Trip | None:
    return (
        await db.execute(
            select(Trip).where(Trip.id == trip_id).options(selectinload(Trip.waypoints))
        )
    ).scalar_one_or_none()


@activity.defn
async def rescore_trip_activity(trip_id: str) -> RescoreResult:
    """Fetch conditions + score + persist + notify (the existing runner). The
    one activity that does the heavy lifting; retried automatically on failure."""
    async with _sessionmaker()() as db:
        async with db.begin():
            trip = await _load_trip(db, trip_id)
            if trip is None or not trip.waypoints:
                activity.logger.info(f"trip {trip_id} not scorable yet")
                return RescoreResult(trip_id=trip_id, found=False)
            result = await rescore_trip(db, trip)
            return RescoreResult(
                trip_id=trip_id,
                found=True,
                score=result.score,
                feasible=result.feasible,
                turn_around_deadline=(
                    result.turn_around_deadline.isoformat()
                    if result.turn_around_deadline
                    else None
                ),
                status=trip.status,
            )


@activity.defn
async def recompute_copilot_activity(trip_id: str, lat: float, lon: float) -> RescoreResult:
    """Underway: a position arrived. For the POC we re-run the full rescore (it
    already recomputes the turn-around deadline); a production cut would do a
    lighter position-relative calc. Returns the live co-pilot numbers."""
    async with _sessionmaker()() as db:
        async with db.begin():
            trip = await _load_trip(db, trip_id)
            if trip is None or not trip.waypoints:
                return RescoreResult(trip_id=trip_id, found=False)
            result = await rescore_trip(db, trip)
            activity.logger.info(
                f"co-pilot {trip_id} @ {lat:.4f},{lon:.4f}: score {result.score}"
            )
            return RescoreResult(
                trip_id=trip_id,
                found=True,
                score=result.score,
                feasible=result.feasible,
                turn_around_deadline=(
                    result.turn_around_deadline.isoformat()
                    if result.turn_around_deadline
                    else None
                ),
                status=trip.status,
            )


@activity.defn
async def generate_debrief_activity(trip_id: str) -> None:
    """Window closed — drop a debrief notification. Placeholder for the LLM
    debrief (backlog D-tier); proves the post-trip phase of the workflow runs."""
    async with _sessionmaker()() as db:
        async with db.begin():
            trip = await _load_trip(db, trip_id)
            if trip is None:
                return
            db.add(
                Notification(
                    user_id=trip.user_id,
                    trip_id=trip.id,
                    type="departure_reminder",
                    channel="in_app",
                    subject=f"Trip complete: {trip.name or 'your trip'}",
                    body="Your window has closed. A debrief comparing planned vs "
                    "actual will appear here.",
                )
            )
