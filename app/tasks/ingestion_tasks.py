import asyncio
from uuid import UUID

from celery.signals import worker_process_init

from app.tasks.celery_app import celery_app


@worker_process_init.connect
def preload_gliner_model(**kwargs) -> None:
    """Loads GliNER once per worker process (not per task) so /upload responses stay fast."""
    from app.services.ingestion_service import get_gliner_model

    get_gliner_model()


# Registered only because app/tasks/celery_app.py imports this module explicitly.
# New task modules must be added to that import list too, or the worker never sees them.
@celery_app.task(name="ingestion.process_cv")
def process_cv_task(cv_id: str) -> None:
    from app.db.postgres import SessionLocal
    from app.services.ingestion_service import run_pipeline

    async def _run() -> None:
        async with SessionLocal() as db:
            await run_pipeline(db, UUID(cv_id))

    asyncio.run(_run())


# Registered only because app/tasks/celery_app.py imports this module explicitly.
@celery_app.task(name="ingestion.trigger_indexing")
def trigger_indexing(cv_id: str) -> None:
    from app.tasks.entity_resolution_tasks import index_candidat_task

    index_candidat_task.delay(cv_id)
