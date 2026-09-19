import pytest
from httpx import AsyncClient

from app.core.rate_limit import limiter


@pytest.mark.asyncio
async def test_login_is_rate_limited_after_five_attempts_per_minute(client: AsyncClient):
    limiter.enabled = True
    try:
        for _ in range(5):
            await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"})

        response = await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
        )
        assert response.status_code == 429
    finally:
        limiter.enabled = False
