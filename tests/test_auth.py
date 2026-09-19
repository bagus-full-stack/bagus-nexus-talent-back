import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole


async def _create_user(db: AsyncSession, email: str, password: str, role: UserRole = UserRole.ADMIN) -> User:
    user = User(email=email, nom="Test User", mot_de_passe_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_login_success_returns_tokens(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "admin@example.com", "Passw0rd!")

    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "Passw0rd!"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "admin@example.com", "Passw0rd!")

    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_recruteur_forbidden_on_list_users(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "recruteur@example.com", "Passw0rd!", role=UserRole.RECRUTEUR)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "recruteur@example.com", "password": "Passw0rd!"}
    )
    token = login.json()["access_token"]

    response = await client.get("/api/v1/users/", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invite_existing_email_returns_409(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "admin@example.com", "Passw0rd!")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "Passw0rd!"}
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/users/invite",
        json={"email": "admin@example.com", "role": "recruteur"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
