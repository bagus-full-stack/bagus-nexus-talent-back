from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import send_email_dev
from app.core.security import generate_temporary_password, hash_password
from app.models.notification import NotificationType
from app.models.user import User, UserRole, UserStatus
from app.schemas.user import PaginatedUsers, UserRead
from app.services.notification_service import notifier_roles


async def list_users(db: AsyncSession, page: int, limit: int) -> PaginatedUsers:
    total = await db.scalar(select(func.count()).select_from(User))
    result = await db.execute(
        select(User).order_by(User.date_creation).offset((page - 1) * limit).limit(limit)
    )
    items = result.scalars().all()
    return PaginatedUsers(
        items=[UserRead.model_validate(u) for u in items],
        page=page,
        limit=limit,
        total=total or 0,
    )


async def invite_user(db: AsyncSession, email: str, role: UserRole, invited_by: UUID) -> User:
    temp_password = generate_temporary_password()
    user = User(
        email=email,
        nom=email.split("@")[0],
        mot_de_passe_hash=hash_password(temp_password),
        role=role,
        statut=UserStatus.INVITATION_EN_ATTENTE,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    send_email_dev(
        email,
        "Invitation NexusTalent",
        f"Vous avez été invité en tant que {role.value}. Mot de passe temporaire : {temp_password}",
    )
    await notifier_roles(
        db,
        (UserRole.ADMIN,),
        NotificationType.INVITATION_ENVOYEE,
        f"{email} a été invité en tant que {role.value}.",
        exclude_user_id=invited_by,
    )
    return user


async def update_user_role(db: AsyncSession, user_id: UUID, role: UserRole) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def revoke_user(db: AsyncSession, user_id: UUID) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.statut = UserStatus.REVOQUE
    await db.commit()
    await db.refresh(user)
    return user
