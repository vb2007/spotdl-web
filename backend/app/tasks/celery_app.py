from celery import Celery
from kombu import Queue

from app.config import get_settings

settings = get_settings()

celery_app = Celery("spotdl_web", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_default_queue="meta",
    task_queues=(Queue("meta"), Queue("downloads")),
    task_routes={
        "app.tasks.download.*": {"queue": "downloads"},
    },
    timezone="UTC",
    enable_utc=True,
)
