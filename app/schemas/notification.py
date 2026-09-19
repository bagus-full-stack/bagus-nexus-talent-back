import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    texte: str
    lu: bool
    date_creation: datetime


class PaginatedNotifications(BaseModel):
    items: list[NotificationRead]
    page: int
    limit: int
    total: int
    non_lues: int
