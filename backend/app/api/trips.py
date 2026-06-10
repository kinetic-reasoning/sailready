import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import Boat, RouteWaypoint, Trip
from app.schemas import (
    Envelope,
    LocationIn,
    LocationOut,
    TripDetailOut,
    TripIn,
    TripOut,
    TripStatusIn,
    WaypointOut,
    WaypointsReplaceIn,
)

router = APIRouter(prefix="/trips", tags=["trips"])

VALID_TRANSITIONS: dict[str, set[str]] = {
    "planning": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def point_expr(loc: LocationIn):
    """Build a PostGIS point from lat/lon — parameterized, no string formatting."""
    return func.ST_SetSRID(func.ST_MakePoint(loc.lon, loc.lat), 4326)


def location_out(geom, name: str | None) -> LocationOut:
    pt = to_shape(geom)
    return LocationOut(lat=pt.y, lon=pt.x, name=name)


def waypoint_out(wp: RouteWaypoint) -> WaypointOut:
    pt = to_shape(wp.location)
    return WaypointOut(
        sequence_order=wp.sequence_order,
        lat=pt.y,
        lon=pt.x,
        name=wp.name,
        waypoint_type=wp.waypoint_type,
        is_auto_routed=wp.is_auto_routed,
        leg_mode=wp.leg_mode,
        depth_acknowledged=wp.depth_acknowledged,
    )


def trip_out(trip: Trip) -> TripOut:
    return TripOut(
        id=trip.id,
        boat_id=trip.boat_id,
        name=trip.name,
        status=trip.status,
        departure_location=location_out(trip.departure_location, trip.departure_location_name),
        destination_location=location_out(
            trip.destination_location, trip.destination_location_name
        ),
        departure_time=trip.departure_time,
        return_by_time=trip.return_by_time,
        time_at_destination_hrs=float(trip.time_at_destination_hrs),
        routing_type=trip.routing_type,
        current_score=trip.current_score,
        current_score_updated_at=trip.current_score_updated_at,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
    )


def trip_detail_out(trip: Trip) -> TripDetailOut:
    return TripDetailOut(
        **trip_out(trip).model_dump(),
        waypoints=[waypoint_out(wp) for wp in trip.waypoints],
    )


async def get_owned_trip(trip_id: uuid.UUID, db: AsyncSession) -> Trip:
    # RLS scopes the query to the current user; missing = 404
    trip = (
        await db.execute(
            select(Trip).where(Trip.id == trip_id).options(selectinload(Trip.waypoints))
        )
    ).scalar_one_or_none()
    if trip is None:
        raise HTTPException(status_code=404, detail="trip not found")
    return trip


async def get_owned_boat_or_400(boat_id: uuid.UUID, db: AsyncSession) -> Boat:
    boat = (await db.execute(select(Boat).where(Boat.id == boat_id))).scalar_one_or_none()
    if boat is None:
        raise HTTPException(status_code=400, detail="boat_id is not one of your boats")
    return boat


def apply_trip_fields(trip: Trip, payload: TripIn) -> None:
    trip.boat_id = payload.boat_id
    trip.name = payload.name
    trip.departure_location = point_expr(payload.departure_location)
    trip.destination_location = point_expr(payload.destination_location)
    trip.departure_location_name = payload.departure_location.name
    trip.destination_location_name = payload.destination_location.name
    trip.departure_time = payload.departure_time
    trip.return_by_time = payload.return_by_time
    trip.time_at_destination_hrs = payload.time_at_destination_hrs


@router.get("", response_model=Envelope[list[TripOut]])
async def list_trips(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    stmt = select(Trip).order_by(Trip.departure_time.desc())
    if status is not None:
        if status not in VALID_TRANSITIONS:
            raise HTTPException(status_code=422, detail=f"invalid status filter: {status}")
        stmt = stmt.where(Trip.status == status)
    trips = (await db.execute(stmt)).scalars().all()
    return Envelope[list[TripOut]](data=[trip_out(t) for t in trips])


@router.post("", response_model=Envelope[TripDetailOut], status_code=201)
async def create_trip(
    payload: TripIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    await get_owned_boat_or_400(payload.boat_id, db)
    trip = Trip(user_id=current.id)
    apply_trip_fields(trip, payload)
    db.add(trip)
    await db.flush()
    trip = await get_owned_trip(trip.id, db)
    return Envelope[TripDetailOut](data=trip_detail_out(trip))


@router.get("/{trip_id}", response_model=Envelope[TripDetailOut])
async def get_trip(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    trip = await get_owned_trip(trip_id, db)
    return Envelope[TripDetailOut](data=trip_detail_out(trip))


@router.put("/{trip_id}", response_model=Envelope[TripDetailOut])
async def update_trip(
    trip_id: uuid.UUID,
    payload: TripIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    trip = await get_owned_trip(trip_id, db)
    if trip.status != "planning":
        raise HTTPException(status_code=409, detail=f"cannot edit a {trip.status} trip")
    await get_owned_boat_or_400(payload.boat_id, db)
    # Note: changing locations may invalidate existing waypoints — the client
    # re-draws the route; a rescore is triggered when scoring lands (step 4).
    apply_trip_fields(trip, payload)
    trip.updated_at = func.now()
    await db.flush()
    trip = await get_owned_trip(trip_id, db)
    return Envelope[TripDetailOut](data=trip_detail_out(trip))


@router.delete("/{trip_id}", response_model=Envelope[dict])
async def delete_trip(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    trip = await get_owned_trip(trip_id, db)
    await db.delete(trip)
    await db.flush()
    return Envelope[dict](data={"deleted": str(trip_id)})


@router.put("/{trip_id}/status", response_model=Envelope[TripOut])
async def update_trip_status(
    trip_id: uuid.UUID,
    payload: TripStatusIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    trip = await get_owned_trip(trip_id, db)
    if payload.status not in VALID_TRANSITIONS[trip.status]:
        raise HTTPException(
            status_code=409,
            detail=f"cannot transition from {trip.status} to {payload.status}",
        )
    trip.status = payload.status
    trip.updated_at = func.now()
    await db.flush()
    trip = await get_owned_trip(trip_id, db)
    return Envelope[TripOut](data=trip_out(trip))


# --- waypoints ----------------------------------------------------------------


@router.get("/{trip_id}/waypoints", response_model=Envelope[list[WaypointOut]])
async def get_waypoints(
    trip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    trip = await get_owned_trip(trip_id, db)
    return Envelope[list[WaypointOut]](data=[waypoint_out(wp) for wp in trip.waypoints])


@router.put("/{trip_id}/waypoints", response_model=Envelope[list[WaypointOut]])
async def replace_waypoints(
    trip_id: uuid.UUID,
    payload: WaypointsReplaceIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    """Full replace — the user redraws the route. First point is the start,
    last is the destination, everything between is intermediate."""
    trip = await get_owned_trip(trip_id, db)
    if trip.status != "planning":
        raise HTTPException(status_code=409, detail=f"cannot edit route of a {trip.status} trip")
    if (
        payload.expected_updated_at is not None
        and trip.updated_at != payload.expected_updated_at
    ):
        raise HTTPException(
            status_code=409,
            detail="trip was modified elsewhere — reload the page and retry",
        )

    await db.execute(delete(RouteWaypoint).where(RouteWaypoint.trip_id == trip_id))

    last = len(payload.waypoints) - 1
    for i, wp in enumerate(payload.waypoints):
        wp_type = "start" if i == 0 else "destination" if i == last else "intermediate"
        db.add(
            RouteWaypoint(
                trip_id=trip_id,
                sequence_order=i,
                location=func.ST_SetSRID(func.ST_MakePoint(wp.lon, wp.lat), 4326),
                name=wp.name,
                waypoint_type=wp_type,
                is_auto_routed=False,
                leg_mode=wp.leg_mode,
                depth_acknowledged=wp.depth_acknowledged,
            )
        )

    trip.routing_type = "manual"
    trip.updated_at = func.now()
    await db.flush()
    # Rescore triggers here once the scoring engine lands (build sequence step 4)

    trip = await get_owned_trip(trip_id, db)
    return Envelope[list[WaypointOut]](data=[waypoint_out(wp) for wp in trip.waypoints])
