import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class GDPRRequestType(str, enum.Enum):
    SUPPRESSION = "suppression"
    ANONYMISATION = "anonymisation"


class GDPRRequestStatus(str, enum.Enum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    TERMINEE = "terminee"
    ECHEC = "echec"


class GDPRRequest(Base):
    __tablename__ = "gdpr_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cvs.id"), nullable=False)
    type: Mapped[GDPRRequestType] = mapped_column(Enum(GDPRRequestType, name="gdpr_request_type"), nullable=False)
    statut: Mapped[GDPRRequestStatus] = mapped_column(
        Enum(GDPRRequestStatus, name="gdpr_request_status"), default=GDPRRequestStatus.EN_ATTENTE, nullable=False
    )
    date_creation: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    date_execution: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resultat_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    demande_par: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
