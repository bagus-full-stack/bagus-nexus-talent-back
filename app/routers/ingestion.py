import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import require_role
from app.db.postgres import get_db
from app.models.cv import CV, CVStatus
from app.models.user import UserRole
from app.schemas.cv import (
    CVDetail,
    CVStatusResponse,
    CVUploadResponse,
    CVValidateRequest,
    PaginatedCVs,
)
from app.tasks.ingestion_tasks import process_cv_task, trigger_indexing

router = APIRouter(
    prefix="/api/v1/ingestion",
    tags=["ingestion"],
    dependencies=[Depends(require_role(UserRole.RH_INTERNE, UserRole.ADMIN))],
)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 Mo
UPLOAD_DIR = Path(settings.CV_STORAGE_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", response_model=list[CVUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_cvs(files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    results = []
    for file in files:
        extension = Path(file.filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Extension non supportée: {extension}. Formats acceptés : .pdf, .docx, .txt",
            )

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Le fichier dépasse la taille maximale de 10 Mo",
            )

        cv_id = uuid.uuid4()
        storage_path = UPLOAD_DIR / f"{cv_id}{extension}"
        storage_path.write_bytes(content)

        cv = CV(id=cv_id, nom_fichier=file.filename, storage_path=str(storage_path), statut=CVStatus.EN_COURS)
        db.add(cv)
        await db.commit()

        process_cv_task.delay(str(cv_id))
        results.append(CVUploadResponse(id=cv_id, statut=cv.statut))

    return results


@router.get("/", response_model=PaginatedCVs)
async def list_cvs(
    page: int = 1,
    limit: int = 20,
    statut: CVStatus | None = None,
    recherche: str | None = Query(None, description="Recherche par nom de fichier"),
    tri: str = Query("date_upload", pattern="^(date_upload|nom_fichier|statut)$"),
    ordre: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    query = select(CV)
    count_query = select(func.count()).select_from(CV)

    if statut is not None:
        query = query.where(CV.statut == statut)
        count_query = count_query.where(CV.statut == statut)
    if recherche:
        query = query.where(CV.nom_fichier.ilike(f"%{recherche}%"))
        count_query = count_query.where(CV.nom_fichier.ilike(f"%{recherche}%"))

    sort_col = getattr(CV, tri)
    query = query.order_by(sort_col.desc() if ordre == "desc" else sort_col.asc())
    query = query.offset((page - 1) * limit).limit(limit)

    total = await db.scalar(count_query)
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedCVs(items=items, page=page, limit=limit, total=total or 0)


@router.get("/{cv_id}", response_model=CVDetail)
async def get_cv(cv_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cv = await db.get(CV, cv_id)
    if cv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV introuvable")
    return cv


@router.get("/{cv_id}/status", response_model=CVStatusResponse)
async def get_cv_status(cv_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cv = await db.get(CV, cv_id)
    if cv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV introuvable")
    return CVStatusResponse(id=cv.id, statut=cv.statut)


@router.patch("/{cv_id}/validate", response_model=CVDetail)
async def validate_cv(cv_id: uuid.UUID, data: CVValidateRequest, db: AsyncSession = Depends(get_db)):
    cv = await db.get(CV, cv_id)
    if cv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV introuvable")

    cv.donnees_json = data.donnees.model_dump(mode="json")
    cv.champs_a_verifier = []
    cv.statut = CVStatus.OK
    if data.donnees.source_confiance:
        cv.score_confiance_global = round(
            sum(data.donnees.source_confiance.values()) / len(data.donnees.source_confiance), 2
        )
    await db.commit()
    await db.refresh(cv)

    trigger_indexing.delay(str(cv_id))
    return cv


@router.delete("/{cv_id}/reject", response_model=CVStatusResponse)
async def reject_cv(cv_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cv = await db.get(CV, cv_id)
    if cv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV introuvable")

    cv.statut = CVStatus.REJETE
    await db.commit()
    return CVStatusResponse(id=cv.id, statut=cv.statut)
