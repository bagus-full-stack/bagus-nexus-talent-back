import uuid

from sqlalchemy import Boolean, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ParametresGlobaux(Base):
    """Singleton row (see get_parametres_globaux) holding admin-configurable search settings."""

    __tablename__ = "parametres_globaux"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seuil_confiance_min: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    top_k_llm: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    anonymisation_par_defaut: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
