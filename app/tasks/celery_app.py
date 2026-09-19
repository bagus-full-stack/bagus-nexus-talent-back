from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("nexustalent", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

# autodiscover_tasks(["app.tasks"]) looks for a submodule "app.tasks.tasks"
# (Celery's default related_name), which does not exist here - a real worker
# process would register zero tasks. Import each task module explicitly
# instead. Any new task module must be added to this list, or the worker
# will silently never see it (NotRegistered at execution time).
from app.tasks import ingestion_tasks, entity_resolution_tasks, gdpr_tasks  # noqa: E402,F401

celery_app.conf.beat_schedule = {
    "nettoyage-entites-orphelines-hebdomadaire": {
        "task": "gdpr.nettoyer_entites_orphelines",
        "schedule": crontab(day_of_week=0, hour=3, minute=0),
    }
}
