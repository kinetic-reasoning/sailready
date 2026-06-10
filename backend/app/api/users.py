from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import Boat, User
from app.schemas import Envelope, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=Envelope[UserOut])
async def get_me(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == current.id))).scalar_one()
    return Envelope[UserOut](data=UserOut.model_validate(user))


@router.put("/me", response_model=Envelope[UserOut])
async def update_me(
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == current.id))).scalar_one()

    updates = payload.model_dump(exclude_unset=True)

    # default_boat_id must reference a boat this user owns (RLS scopes the lookup)
    if updates.get("default_boat_id") is not None:
        boat = (
            await db.execute(select(Boat).where(Boat.id == updates["default_boat_id"]))
        ).scalar_one_or_none()
        if boat is None:
            raise HTTPException(status_code=400, detail="default_boat_id is not one of your boats")

    for field, value in updates.items():
        setattr(user, field, value)

    await db.flush()
    return Envelope[UserOut](data=UserOut.model_validate(user))
