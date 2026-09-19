import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole, UserStatus


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    email: EmailStr
    role: UserRole
    statut: UserStatus
    date_creation: datetime


class PaginatedUsers(BaseModel):
    items: list[UserRead]
    page: int
    limit: int
    total: int


class InviteUserRequest(BaseModel):
    email: EmailStr
    role: UserRole


class UpdateRoleRequest(BaseModel):
    role: UserRole
