from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("nexustalent", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.autodiscover_tasks(["app.tasks"])

celery_app.conf.beat_schedule = {
    "nettoyage-entites-orphelines-hebdomadaire": {
        "task": "gdpr.nettoyer_entites_orphelines",
        "schedule": crontab(day_of_week=0, hour=3, minute=0),
    }
}
