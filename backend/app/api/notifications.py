import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import Notification
from app.schemas import Envelope, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Envelope[list[NotificationOut]])
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    items = (
        (
            await db.execute(
                select(Notification).order_by(
                    Notification.read_at.isnot(None),  # unread first
                    Notification.sent_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return Envelope[list[NotificationOut]](
        data=[NotificationOut.model_validate(n) for n in items]
    )


@router.put("/{notification_id}/read", response_model=Envelope[NotificationOut])
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    notification = (
        await db.execute(select(Notification).where(Notification.id == notification_id))
    ).scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="notification not found")
    if notification.read_at is None:
        notification.read_at = func.now()
        await db.flush()
        await db.refresh(notification)
    return Envelope[NotificationOut](data=NotificationOut.model_validate(notification))


@router.put("/read-all", response_model=Envelope[dict])
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(
        update(Notification).where(Notification.read_at.is_(None)).values(read_at=func.now())
    )
    return Envelope[dict](data={"marked_read": result.rowcount})
