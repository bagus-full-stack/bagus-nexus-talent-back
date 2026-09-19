import asyncio
from uuid import UUID

from app.tasks.celery_app import celery_app


@celery_app.task(name="graph.index_candidat")
def index_candidat_task(cv_id: str) -> None:
    from app.db.neo4j import driver as neo4j_driver
    from app.db.postgres import SessionLocal
    from app.db.qdrant import get_qdrant_client
    from app.models.cv import CV
    from app.schemas.candidat import CandidatCV
    from app.services.graph_service import index_candidat_graph, index_candidat_qdrant

    async def _run() -> None:
        async with SessionLocal() as db:
            cv = await db.get(CV, UUID(cv_id))
            if cv is None or not cv.donnees_json:
                return

            candidat = CandidatCV.model_validate(cv.donnees_json)
            qdrant = get_qdrant_client()

            await index_candidat_qdrant(qdrant, cv_id, candidat)

            async with neo4j_driver.session() as neo4j_session:
                await index_candidat_graph(neo4j_session, db, qdrant, cv_id, candidat)

    asyncio.run(_run())
