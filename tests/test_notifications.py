import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.notification_service import notifier_roles


async def _create_user(db: AsyncSession, email: str, role: UserRole, password: str = "Passw0rd!") -> User:
    user = User(email=email, nom=email.split("@")[0], mot_de_passe_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


# ---- Déclencheur : notification créée à l'échec du parsing CV ----------------

@pytest.mark.asyncio
async def test_notification_created_on_cv_parsing_failure(db_session: AsyncSession):
    admin = await _create_user(db_session, "admin-notif@example.com", UserRole.ADMIN)
    recruteur = await _create_user(db_session, "recruteur-notif@example.com", UserRole.RECRUTEUR)

    await notifier_roles(
        db_session,
        (UserRole.ADMIN, UserRole.RH_INTERNE),
        NotificationType.CV_ECHEC,
        "Échec du parsing pour le CV « cv.pdf ».",
    )

    result = await db_session.execute(select(Notification).where(Notification.user_id == admin.id))
    notifications = result.scalars().all()
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.CV_ECHEC

    result = await db_session.execute(select(Notification).where(Notification.user_id == recruteur.id))
    assert result.scalars().first() is None


# ---- Paramètres de recherche : validation et contrôle d'accès ----------------

@pytest.mark.asyncio
async def test_update_search_config_rejects_top_k_llm_out_of_range(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "admin-settings@example.com", UserRole.ADMIN)
    token = await _login(client, "admin-settings@example.com", "Passw0rd!")

    response = await client.patch(
        "/api/v1/settings/search-config",
        json={"top_k_llm": 20},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_recruteur_cannot_update_search_config(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "recruteur-settings@example.com", UserRole.RECRUTEUR)
    token = await _login(client, "recruteur-settings@example.com", "Passw0rd!")

    response = await client.patch(
        "/api/v1/settings/search-config",
        json={"top_k_llm": 10},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
