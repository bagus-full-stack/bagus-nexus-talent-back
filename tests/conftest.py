import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.base import Base
from app.db.postgres import get_db
from app.main import app
from app.models.user import User, UserRole

engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=None)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

DEFAULT_PASSWORD = "Passw0rd!"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    """Factory fixture: creates a persisted user with the given role (one per role, as needed)."""

    async def _make_user(role: UserRole, email: str | None = None, password: str = DEFAULT_PASSWORD) -> User:
        email = email or f"{role.value}-{uuid.uuid4().hex[:8]}@example.com"
        user = User(email=email, nom=role.value, mot_de_passe_hash=hash_password(password), role=role)
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make_user


@pytest_asyncio.fixture
async def login_as(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> Callable[..., Awaitable[tuple[User, dict[str, str]]]]:
    """Factory fixture: creates a user of the given role and logs them in, returning
    (user, auth_headers) so tests can call the shared `client` fixture as that role."""

    async def _login_as(role: UserRole, password: str = DEFAULT_PASSWORD) -> tuple[User, dict[str, str]]:
        user = await make_user(role, password=password)
        response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
        token = response.json()["access_token"]
        return user, {"Authorization": f"Bearer {token}"}

    return _login_as
