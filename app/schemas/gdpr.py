import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.gdpr_request import GDPRRequestStatus, GDPRRequestType


class GDPRRequestCreate(BaseModel):
    candidat_id: uuid.UUID
    type: GDPRRequestType


class GDPRRequestExecute(BaseModel):
    password: str


class GDPRRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidat_id: uuid.UUID
    type: GDPRRequestType
    statut: GDPRRequestStatus
    date_creation: datetime
    date_execution: datetime | None
    resultat_json: dict | None
    demande_par: uuid.UUID


class PaginatedGDPRRequests(BaseModel):
    items: list[GDPRRequestRead]
    page: int
    limit: int
    total: int
