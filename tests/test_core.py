import uuid

import pytest
from fastapi import HTTPException

from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.core.dependencies import require_role
from app.models.user import User, UserRole


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_require_role_rejects_wrong_role():
    check = require_role(UserRole.ADMIN)
    recruteur = User(role=UserRole.RECRUTEUR)
    with pytest.raises(HTTPException) as exc:
        await check(current_user=recruteur)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    check = require_role(UserRole.ADMIN)
    admin = User(role=UserRole.ADMIN)
    assert await check(current_user=admin) is admin
