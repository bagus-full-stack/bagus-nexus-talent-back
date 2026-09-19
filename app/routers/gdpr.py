import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.core.security import verify_password
from app.db.neo4j import get_neo4j_session
from app.db.postgres import get_db
from app.db.qdrant import get_qdrant_client
from app.models.gdpr_request import GDPRRequest, GDPRRequestStatus
from app.models.user import User, UserRole
from app.schemas.gdpr import GDPRRequestCreate, GDPRRequestExecute, GDPRRequestRead, PaginatedGDPRRequests
from app.services.gdpr_service import executer_demande

router = APIRouter(
    prefix="/api/v1/gdpr", tags=["gdpr"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)


@router.get("/", response_model=PaginatedGDPRRequests)
async def list_requests(page: int = 1, limit: int = 20, db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(GDPRRequest))
    result = await db.execute(
        select(GDPRRequest).order_by(GDPRRequest.date_creation.desc()).offset((page - 1) * limit).limit(limit)
    )
    return PaginatedGDPRRequests(items=result.scalars().all(), page=page, limit=limit, total=total or 0)


@router.post("/", response_model=GDPRRequestRead, status_code=status.HTTP_201_CREATED)
async def create_request(
    data: GDPRRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    demande = GDPRRequest(candidat_id=data.candidat_id, type=data.type, demande_par=current_user.id)
    db.add(demande)
    await db.commit()
    await db.refresh(demande)
    return demande


@router.get("/{request_id}", response_model=GDPRRequestRead)
async def get_request(request_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    demande = await db.get(GDPRRequest, request_id)
    if demande is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable")
    return demande


@router.post("/{request_id}/execute", response_model=GDPRRequestRead)
async def execute_request(
    request_id: uuid.UUID,
    body: GDPRRequestExecute,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    qdrant=Depends(get_qdrant_client),
    neo4j_session=Depends(get_neo4j_session),
):
    demande = await db.get(GDPRRequest, request_id)
    if demande is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande introuvable")

    if demande.statut in (GDPRRequestStatus.EN_COURS, GDPRRequestStatus.TERMINEE):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Demande déjà en cours ou terminée")

    # Ré-authentification : vérifie le mot de passe de l'admin courant, pas juste sa session.
    if not verify_password(body.password, current_user.mot_de_passe_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Mot de passe incorrect")

    return await executer_demande(db, qdrant, neo4j_session, demande)
