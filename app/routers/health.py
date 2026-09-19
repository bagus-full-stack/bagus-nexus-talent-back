from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.neo4j import driver as neo4j_driver
from app.db.postgres import get_db
from app.db.qdrant import get_qdrant_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    statuses: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        statuses["postgres"] = "ok"
    except Exception as exc:
        statuses["postgres"] = f"error: {exc}"

    try:
        await neo4j_driver.verify_connectivity()
        statuses["neo4j"] = "ok"
    except Exception as exc:
        statuses["neo4j"] = f"error: {exc}"

    try:
        await get_qdrant_client().get_collections()
        statuses["qdrant"] = "ok"
    except Exception as exc:
        statuses["qdrant"] = f"error: {exc}"

    overall = "ok" if all(v == "ok" for v in statuses.values()) else "degraded"
    return {"status": overall, "services": statuses}
