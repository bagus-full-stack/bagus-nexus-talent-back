import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_preference import DEFAULT_PREFERENCES, NotificationPreference
from app.schemas.settings import NotificationPreferencesRead, NotificationPreferencesUpdate, SearchConfigUpdate
from app.services.search_service import get_parametres_globaux


async def update_search_config(db: AsyncSession, data: SearchConfigUpdate):
    parametres = await get_parametres_globaux(db)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(parametres, field, value)
    await db.commit()
    await db.refresh(parametres)
    return parametres


async def _get_or_create_preferences(db: AsyncSession, user_id: uuid.UUID) -> NotificationPreference:
    result = await db.execute(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    preference = result.scalars().first()
    if preference is None:
        preference = NotificationPreference(user_id=user_id, preferences={})
        db.add(preference)
        await db.commit()
        await db.refresh(preference)
    return preference


async def get_notification_preferences(db: AsyncSession, user_id: uuid.UUID) -> NotificationPreferencesRead:
    preference = await _get_or_create_preferences(db, user_id)
    merged = {**DEFAULT_PREFERENCES, **preference.preferences}
    return NotificationPreferencesRead.model_validate(merged)


async def update_notification_preferences(
    db: AsyncSession, user_id: uuid.UUID, data: NotificationPreferencesUpdate
) -> NotificationPreferencesRead:
    preference = await _get_or_create_preferences(db, user_id)
    merged = {**DEFAULT_PREFERENCES, **preference.preferences}
    for event_type, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        merged[event_type] = value
    preference.preferences = merged
    await db.commit()
    await db.refresh(preference)
    return NotificationPreferencesRead.model_validate(merged)
