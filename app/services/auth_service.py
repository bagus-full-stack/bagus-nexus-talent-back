from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import send_email_dev
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_reset_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserStatus
from app.schemas.auth import LoginResponse, UserPublic

RESET_TOKEN_TTL_SECONDS = 30 * 60
RESET_TOKEN_PREFIX = "pwd-reset:"


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None or not verify_password(password, user.mot_de_passe_hash):
        return None
    return user


def build_login_response(user: User) -> LoginResponse:
    return LoginResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserPublic.model_validate(user),
    )


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str | None:
    try:
        payload = decode_token(refresh_token)
    except ValueError:
        return None
    if payload.get("type") != "refresh":
        return None

    user = await db.get(User, UUID(payload["sub"]))
    if user is None or user.statut != UserStatus.ACTIF:
        return None
    return create_access_token(user.id)


async def request_password_reset(db: AsyncSession, redis: Redis, email: str) -> None:
    user = await get_user_by_email(db, email)
    if user is None:
        return  # caller always returns a generic message - no account enumeration

    token = generate_reset_token()
    await redis.set(f"{RESET_TOKEN_PREFIX}{token}", str(user.id), ex=RESET_TOKEN_TTL_SECONDS)
    send_email_dev(
        user.email,
        "Réinitialisation de mot de passe",
        f"Lien de réinitialisation (valide 30 min) : https://app.nexustalent.io/reset-password?token={token}",
    )


async def reset_password(db: AsyncSession, redis: Redis, token: str, new_password: str) -> bool:
    key = f"{RESET_TOKEN_PREFIX}{token}"
    user_id = await redis.get(key)
    if user_id is None:
        return False

    user = await db.get(User, UUID(user_id))
    if user is None:
        await redis.delete(key)
        return False

    user.mot_de_passe_hash = hash_password(new_password)
    await db.commit()
    await redis.delete(key)
    return True
