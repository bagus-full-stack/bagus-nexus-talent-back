from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class Competence(BaseModel):
    nom: str
    niveau: str | None = None
    confiance: float = Field(default=0.0, ge=0.0, le=1.0)


class Diplome(BaseModel):
    intitule: str
    etablissement: str | None = None
    annee_obtention: int | None = None
    confiance: float = Field(default=0.0, ge=0.0, le=1.0)


class ExperiencePro(BaseModel):
    poste: str
    entreprise: str | None = None
    date_debut: date
    date_fin: date | None = None  # None = poste actuel
    description: str | None = None
    confiance: float = Field(default=0.0, ge=0.0, le=1.0)


class CandidatCV(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    email: EmailStr | None = None
    telephone: str | None = None
    localisation: str | None = None
    langue_detectee: str | None = None
    disponible_a_partir_de: date | None = None
    competences: list[Competence] = Field(default_factory=list)
    diplomes: list[Diplome] = Field(default_factory=list)
    experiences: list[ExperiencePro] = Field(default_factory=list)
    annees_experience_cumulees: float | None = None
    source_confiance: dict[str, float] = Field(default_factory=dict)
    statut_qualite: Literal["ok", "a_valider", "echec_parsing"] = "a_valider"
    champs_a_verifier: list[str] = Field(default_factory=list)
