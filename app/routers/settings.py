import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.db.postgres import get_db
from app.models.synonym import SynonymePaire
from app.models.user import User, UserRole
from app.schemas.settings import (
    NotificationPreferencesRead,
    NotificationPreferencesUpdate,
    SearchConfigRead,
    SearchConfigUpdate,
)
from app.schemas.synonym import PaginatedSynonymes, SynonymeCreate, SynonymeRead
from app.services import settings_service
from app.services.search_service import get_parametres_globaux

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ---- Synonymes (admin uniquement) --------------------------------------------

@router.get(
    "/synonyms/", response_model=PaginatedSynonymes, dependencies=[Depends(require_role(UserRole.ADMIN))]
)
async def list_synonyms(page: int = 1, limit: int = 20, db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(SynonymePaire))
    result = await db.execute(select(SynonymePaire).offset((page - 1) * limit).limit(limit))
    items = result.scalars().all()
    return PaginatedSynonymes(items=items, page=page, limit=limit, total=total or 0)


@router.post(
    "/synonyms/",
    response_model=SynonymeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def create_synonym(data: SynonymeCreate, db: AsyncSession = Depends(get_db)):
    pair = SynonymePaire(terme_a=data.terme_a, terme_b=data.terme_b, type_entite=data.type_entite)
    db.add(pair)
    await db.commit()
    await db.refresh(pair)
    return pair


@router.delete(
    "/synonyms/{synonym_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_synonym(synonym_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    pair = await db.get(SynonymePaire, synonym_id)
    if pair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Synonyme introuvable")
    await db.delete(pair)
    await db.commit()


# ---- Configuration de recherche (rh_interne, admin) --------------------------

@router.get(
    "/search-config",
    response_model=SearchConfigRead,
    dependencies=[Depends(require_role(UserRole.RH_INTERNE, UserRole.ADMIN))],
)
async def get_search_config(db: AsyncSession = Depends(get_db)):
    return await get_parametres_globaux(db)


@router.patch(
    "/search-config",
    response_model=SearchConfigRead,
    dependencies=[Depends(require_role(UserRole.RH_INTERNE, UserRole.ADMIN))],
)
async def update_search_config(data: SearchConfigUpdate, db: AsyncSession = Depends(get_db)):
    return await settings_service.update_search_config(db, data)


# ---- Préférences de notification (tout utilisateur authentifié) --------------

@router.get("/notification-preferences", response_model=NotificationPreferencesRead)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await settings_service.get_notification_preferences(db, current_user.id)


@router.patch("/notification-preferences", response_model=NotificationPreferencesRead)
async def update_notification_preferences(
    data: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await settings_service.update_notification_preferences(db, current_user.id, data)
