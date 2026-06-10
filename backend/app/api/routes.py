import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.trips import get_owned_boat_or_400, get_owned_trip, location_out, trip_detail_out
from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import RouteWaypoint, SavedRoute, Trip, User
from app.schemas import (
    Envelope,
    SavedRouteIn,
    SavedRouteOut,
    SavedRouteWaypoint,
    TripDetailOut,
    TripFromRouteIn,
)

router = APIRouter(prefix="/routes", tags=["saved-routes"])


def saved_route_out(r: SavedRoute) -> SavedRouteOut:
    return SavedRouteOut(
        id=r.id,
        name=r.name,
        departure_location=location_out(r.departure_location, None),
        destination_location=location_out(r.destination_location, None),
        waypoints=[SavedRouteWaypoint(**wp) for wp in r.waypoints],
        notes=r.notes,
        created_at=r.created_at,
        last_used_at=r.last_used_at,
    )


async def get_owned_route(route_id: uuid.UUID, db: AsyncSession) -> SavedRoute:
    route = (
        await db.execute(select(SavedRoute).where(SavedRoute.id == route_id))
    ).scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="saved route not found")
    return route


@router.get("", response_model=Envelope[list[SavedRouteOut]])
async def list_routes(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    routes = (
        (await db.execute(select(SavedRoute).order_by(SavedRoute.created_at))).scalars().all()
    )
    return Envelope[list[SavedRouteOut]](data=[saved_route_out(r) for r in routes])


@router.post("", response_model=Envelope[SavedRouteOut], status_code=201)
async def create_route(
    payload: SavedRouteIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    route = SavedRoute(
        user_id=current.id,
        name=payload.name,
        departure_location=func.ST_SetSRID(
            func.ST_MakePoint(payload.departure_location.lon, payload.departure_location.lat), 4326
        ),
        destination_location=func.ST_SetSRID(
            func.ST_MakePoint(payload.destination_location.lon, payload.destination_location.lat),
            4326,
        ),
        waypoints=[wp.model_dump() for wp in payload.waypoints],
        notes=payload.notes,
    )
    db.add(route)
    await db.flush()
    route = await get_owned_route(route.id, db)
    return Envelope[SavedRouteOut](data=saved_route_out(route))


@router.get("/{route_id}", response_model=Envelope[SavedRouteOut])
async def get_route(
    route_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    route = await get_owned_route(route_id, db)
    return Envelope[SavedRouteOut](data=saved_route_out(route))


@router.delete("/{route_id}", response_model=Envelope[dict])
async def delete_route(
    route_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    route = await get_owned_route(route_id, db)
    await db.delete(route)
    await db.flush()
    return Envelope[dict](data={"deleted": str(route_id)})


@router.post("/{route_id}/trip", response_model=Envelope[TripDetailOut], status_code=201)
async def create_trip_from_route(
    route_id: uuid.UUID,
    payload: TripFromRouteIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    route = await get_owned_route(route_id, db)

    boat_id = payload.boat_id
    if boat_id is None:
        user = (await db.execute(select(User).where(User.id == current.id))).scalar_one()
        boat_id = user.default_boat_id
    if boat_id is None:
        raise HTTPException(status_code=400, detail="no boat_id given and no default boat set")
    await get_owned_boat_or_400(boat_id, db)

    template = route.waypoints
    trip = Trip(
        user_id=current.id,
        boat_id=boat_id,
        name=payload.name or route.name,
        departure_location=route.departure_location,
        destination_location=route.destination_location,
        departure_location_name=template[0].get("name") if template else None,
        destination_location_name=template[-1].get("name") if template else None,
        departure_time=payload.departure_time,
        return_by_time=payload.return_by_time,
        time_at_destination_hrs=payload.time_at_destination_hrs,
    )
    db.add(trip)
    await db.flush()

    last = len(template) - 1
    for i, wp in enumerate(template):
        wp_type = "start" if i == 0 else "destination" if i == last else "intermediate"
        db.add(
            RouteWaypoint(
                trip_id=trip.id,
                sequence_order=i,
                location=func.ST_SetSRID(func.ST_MakePoint(wp["lon"], wp["lat"]), 4326),
                name=wp.get("name"),
                waypoint_type=wp_type,
                is_auto_routed=False,
            )
        )

    route.last_used_at = func.now()
    await db.flush()
    trip = await get_owned_trip(trip.id, db)
    return Envelope[TripDetailOut](data=trip_detail_out(trip))
