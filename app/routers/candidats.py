from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.neo4j import get_neo4j_session
from app.db.postgres import get_db
from app.db.qdrant import get_qdrant_client
from app.models.cv import CV
from app.schemas.candidat import CandidatCV
from app.schemas.search import CandidatDetailResponse, SearchQuery, SearchResponse
from app.services.search_service import build_candidat_detail, get_parametres_globaux, hybrid_search

router = APIRouter(prefix="/api/v1/candidats", tags=["candidats"], dependencies=[Depends(get_current_user)])


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchQuery,
    db: AsyncSession = Depends(get_db),
    qdrant=Depends(get_qdrant_client),
    neo4j_session=Depends(get_neo4j_session),
):
    result = await hybrid_search(db, qdrant, neo4j_session, body.query)
    return SearchResponse(**result)


@router.get("/{candidat_id}", response_model=CandidatDetailResponse)
async def get_candidat(candidat_id: str, db: AsyncSession = Depends(get_db)):
    cv = await db.get(CV, candidat_id)
    if cv is None or cv.donnees_json is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidat introuvable")

    candidat = CandidatCV.model_validate(cv.donnees_json)
    parametres = await get_parametres_globaux(db)
    anonymise = cv.anonymise or parametres.anonymisation_par_defaut
    return build_candidat_detail(cv, candidat, anonymise)
