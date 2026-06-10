import math
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import Boat
from app.schemas import BoatIn, BoatOut, Envelope

router = APIRouter(prefix="/boats", tags=["boats"])

# Typical waterline-to-overall length ratio for production cruising sailboats,
# used only when the user hasn't provided hull speed directly.
LWL_TO_LOA_RATIO = 0.85


def derive_hull_speed_kts(loa_ft: float) -> Decimal:
    """Hull speed = 1.34 * sqrt(LWL). LWL estimated from LOA."""
    lwl_ft = loa_ft * LWL_TO_LOA_RATIO
    return Decimal(f"{1.34 * math.sqrt(lwl_ft):.1f}")


def apply_hull_speed(boat: Boat, payload: BoatIn) -> None:
    if payload.hull_speed_kts is None:
        boat.hull_speed_kts = derive_hull_speed_kts(payload.loa_ft)
        boat.hull_speed_is_derived = True
    else:
        boat.hull_speed_kts = Decimal(f"{payload.hull_speed_kts:.1f}")
        boat.hull_speed_is_derived = False


async def get_owned_boat(boat_id: uuid.UUID, db: AsyncSession) -> Boat:
    # RLS already scopes the query to the current user; missing = 404
    boat = (await db.execute(select(Boat).where(Boat.id == boat_id))).scalar_one_or_none()
    if boat is None:
        raise HTTPException(status_code=404, detail="boat not found")
    return boat


@router.get("", response_model=Envelope[list[BoatOut]])
async def list_boats(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    boats = (await db.execute(select(Boat).order_by(Boat.created_at))).scalars().all()
    return Envelope[list[BoatOut]](data=[BoatOut.model_validate(b) for b in boats])


@router.post("", response_model=Envelope[BoatOut], status_code=201)
async def create_boat(
    payload: BoatIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    boat = Boat(user_id=current.id, **payload.model_dump(exclude={"hull_speed_kts"}))
    apply_hull_speed(boat, payload)
    db.add(boat)
    await db.flush()
    return Envelope[BoatOut](data=BoatOut.model_validate(boat))


@router.get("/{boat_id}", response_model=Envelope[BoatOut])
async def get_boat(
    boat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    boat = await get_owned_boat(boat_id, db)
    return Envelope[BoatOut](data=BoatOut.model_validate(boat))


@router.put("/{boat_id}", response_model=Envelope[BoatOut])
async def update_boat(
    boat_id: uuid.UUID,
    payload: BoatIn,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    boat = await get_owned_boat(boat_id, db)
    for field, value in payload.model_dump(exclude={"hull_speed_kts"}).items():
        setattr(boat, field, value)
    apply_hull_speed(boat, payload)
    boat.updated_at = func.now()
    await db.flush()
    await db.refresh(boat)
    return Envelope[BoatOut](data=BoatOut.model_validate(boat))


@router.delete("/{boat_id}", response_model=Envelope[dict])
async def delete_boat(
    boat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    boat = await get_owned_boat(boat_id, db)
    await db.delete(boat)
    await db.flush()
    return Envelope[dict](data={"deleted": str(boat_id)})
