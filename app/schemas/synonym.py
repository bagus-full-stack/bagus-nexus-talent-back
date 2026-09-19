import uuid

from pydantic import BaseModel, ConfigDict


class SynonymeCreate(BaseModel):
    terme_a: str
    terme_b: str
    type_entite: str = "competence"


class SynonymeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    terme_a: str
    terme_b: str
    type_entite: str


class PaginatedSynonymes(BaseModel):
    items: list[SynonymeRead]
    page: int
    limit: int
    total: int
