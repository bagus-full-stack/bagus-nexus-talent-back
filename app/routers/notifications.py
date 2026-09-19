import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.postgres import get_db
from app.models.user import User
from app.schemas.notification import NotificationRead, PaginatedNotifications
from app.services import notification_service

router = APIRouter(
    prefix="/api/v1/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)]
)


@router.get("/", response_model=PaginatedNotifications)
async def list_notifications(
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.list_notifications(db, current_user.id, page, limit)


@router.patch("/read-all", response_model=PaginatedNotifications)
async def mark_all_read(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await notification_service.mark_all_read(db, current_user.id)
    return await notification_service.list_notifications(db, current_user.id, page=1, limit=20)


@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notification = await notification_service.mark_read(db, current_user.id, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification introuvable")
    return notification
