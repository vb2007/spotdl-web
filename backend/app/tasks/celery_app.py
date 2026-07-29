import os

from celery import Celery
from celery.signals import worker_ready
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
    beat_schedule={
        "dispatch-due-tracks": {
            "task": "app.tasks.beat.dispatch_due_tracks",
            "schedule": 30.0,
        },
    },
)

# Importing task modules here (after celery_app is defined) registers their @celery_app.task
# decorators with this app — required since the worker command doesn't pass --include.
from app.tasks import download  # noqa: E402,F401
from app.tasks import expand  # noqa: E402,F401
from app.tasks import beat  # noqa: E402,F401


@worker_ready.connect
def _reconcile_disk_on_boot(**kwargs) -> None:
    # Gated by an explicit env var (set only on worker-meta in docker-compose.yml) rather
    # than introspecting which queues this process consumes — reconciliation is a
    # worker-meta concern (see Architecture notes in CLAUDE.md), and this keeps that
    # scoping visible in compose config instead of buried in Celery internals.
    if os.environ.get("RUN_DISK_RECONCILE") == "true":
        from app.services.dedup import reconcile_disk

        reconcile_disk()


@worker_ready.connect
def _sync_proxies_on_boot(**kwargs) -> None:
    # Same explicit-env-var-gate convention as _reconcile_disk_on_boot above — proxies.txt
    # sync is also a worker-meta-only concern.
    if os.environ.get("RUN_PROXY_SYNC") == "true":
        from app.services.proxies import sync_from_file

        sync_from_file()
