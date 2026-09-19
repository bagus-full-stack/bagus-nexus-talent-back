import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CVStatus(str, enum.Enum):
    EN_COURS = "en_cours"
    OK = "ok"
    A_VALIDER = "a_valider"
    ECHEC_PARSING = "echec_parsing"
    REJETE = "rejete"


class CV(Base):
    __tablename__ = "cvs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom_fichier: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    date_upload: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    statut: Mapped[CVStatus] = mapped_column(
        Enum(CVStatus, name="cv_status"), default=CVStatus.EN_COURS, nullable=False
    )
    score_confiance_global: Mapped[float | None] = mapped_column(Float, nullable=True)
    donnees_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    champs_a_verifier: Mapped[list | None] = mapped_column(JSON, nullable=True)
    anonymise: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
