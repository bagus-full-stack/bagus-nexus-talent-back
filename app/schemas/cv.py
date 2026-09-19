import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.cv import CVStatus
from app.schemas.candidat import CandidatCV


class CVUploadResponse(BaseModel):
    id: uuid.UUID
    statut: CVStatus


class CVStatusResponse(BaseModel):
    id: uuid.UUID
    statut: CVStatus


class CVListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom_fichier: str
    date_upload: datetime
    statut: CVStatus
    score_confiance_global: float | None = None


class CVDetail(CVListItem):
    donnees_json: dict | None = None
    champs_a_verifier: list[str] | None = None


class PaginatedCVs(BaseModel):
    items: list[CVListItem]
    page: int
    limit: int
    total: int


class CVValidateRequest(BaseModel):
    donnees: CandidatCV
