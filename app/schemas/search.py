from datetime import date

from pydantic import BaseModel, Field

from app.schemas.candidat import Competence, Diplome, ExperiencePro


class FiltresRecherche(BaseModel):
    experience_min_annees: float | None = None
    competences_requises: list[str] = Field(default_factory=list)
    diplome_min: str | None = None
    langues_requises: list[str] = Field(default_factory=list)
    localisation: str | None = None
    disponibilite_avant: date | None = None


class SearchQuery(BaseModel):
    query: str


class CandidatRecommande(BaseModel):
    candidat_id: str
    justification: str
    elements_cites: list[str] = Field(default_factory=list)
    score: float | None = None


class SyntheseRecherche(BaseModel):
    candidats_recommandes: list[CandidatRecommande] = Field(default_factory=list)
    resume_synthese: str


class SearchResponse(BaseModel):
    filtres_extraits: FiltresRecherche
    candidats: list[CandidatRecommande]
    synthese: str


class CandidatDetailResponse(BaseModel):
    id: str
    nom: str | None = None
    prenom: str | None = None
    email: str | None = None
    telephone: str | None = None
    localisation: str | None = None
    competences: list[Competence] = Field(default_factory=list)
    diplomes: list[Diplome] = Field(default_factory=list)
    experiences: list[ExperiencePro] = Field(default_factory=list)
    annees_experience_cumulees: float | None = None
    statut_qualite: str
