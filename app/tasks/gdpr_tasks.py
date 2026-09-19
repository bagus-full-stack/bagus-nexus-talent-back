import asyncio

from app.tasks.celery_app import celery_app


# Registered only because app/tasks/celery_app.py imports this module explicitly.
# New task modules must be added to that import list too, or the worker never sees them.
@celery_app.task(name="gdpr.nettoyer_entites_orphelines")
def nettoyer_entites_orphelines_task() -> int:
    from app.db.neo4j import driver as neo4j_driver
    from app.services.gdpr_service import nettoyer_entites_orphelines

    async def _run() -> int:
        async with neo4j_driver.session() as session:
            return await nettoyer_entites_orphelines(session)

    return asyncio.run(_run())
