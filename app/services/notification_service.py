import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.schemas.notification import PaginatedNotifications


async def creer_notification(
    db: AsyncSession, user_id: uuid.UUID, type_: NotificationType, texte: str
) -> Notification:
    notification = Notification(user_id=user_id, type=type_, texte=texte)
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def notifier_roles(
    db: AsyncSession,
    roles: tuple[UserRole, ...],
    type_: NotificationType,
    texte: str,
    exclude_user_id: uuid.UUID | None = None,
) -> None:
    """Crée une notification pour chaque utilisateur ayant l'un des rôles donnés."""
    result = await db.execute(select(User.id).where(User.role.in_(roles)))
    for (user_id,) in result.all():
        if user_id == exclude_user_id:
            continue
        db.add(Notification(user_id=user_id, type=type_, texte=texte))
    await db.commit()


async def list_notifications(db: AsyncSession, user_id: uuid.UUID, page: int, limit: int) -> PaginatedNotifications:
    total = await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user_id))
    non_lues = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.lu.is_(False))
    )
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.date_creation.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return PaginatedNotifications(
        items=result.scalars().all(), page=page, limit=limit, total=total or 0, non_lues=non_lues or 0
    )


async def mark_read(db: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        return None
    notification.lu = True
    await db.commit()
    await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification).where(Notification.user_id == user_id, Notification.lu.is_(False)).values(lu=True)
    )
    await db.commit()
