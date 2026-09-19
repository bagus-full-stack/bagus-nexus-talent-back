from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.db.postgres import get_db
from app.models.user import User, UserRole
from app.schemas.user import InviteUserRequest, PaginatedUsers, UpdateRoleRequest, UserRead
from app.services import auth_service, user_service

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.get("/", response_model=PaginatedUsers)
async def list_users(page: int = 1, limit: int = 20, db: AsyncSession = Depends(get_db)):
    return await user_service.list_users(db, page, limit)


@router.post("/invite", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def invite_user(
    data: InviteUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await auth_service.get_user_by_email(db, data.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cet email est déjà utilisé")
    return await user_service.invite_user(db, data.email, data.role, invited_by=current_user.id)


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_role(user_id: UUID, data: UpdateRoleRequest, db: AsyncSession = Depends(get_db)):
    user = await user_service.update_user_role(db, user_id, data.role)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    return user


@router.delete("/{user_id}", response_model=UserRead)
async def revoke_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    user = await user_service.revoke_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    return user
