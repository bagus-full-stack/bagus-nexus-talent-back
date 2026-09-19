import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SynonymePaire(Base):
    __tablename__ = "synonymes_competences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    terme_a: Mapped[str] = mapped_column(String(255), nullable=False)
    terme_b: Mapped[str] = mapped_column(String(255), nullable=False)
    type_entite: Mapped[str] = mapped_column(String(50), default="competence", nullable=False)
