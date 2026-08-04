import os

from celery import Celery
from celery.signals import worker_ready
from kombu import Queue

from app.config import get_settings

# Registers the `setup_logging` receiver (app/logging_config.py) as a side effect of this
# import — must happen before Celery's worker/beat bootstep would otherwise run its own
# default logging setup. Importing here, at the top of the module every worker/beat/api
# process loads via `-A app.tasks.celery_app`, is early enough for that.
from app import logging_config  # noqa: F401

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
    # Durability (v12): with the default task_acks_late=False, a track's broker message is
    # acked *before* download_track's body runs — a `docker compose down`/OOM-kill/host
    # crash mid-download loses that message entirely, stranding the track in `downloading`
    # forever (dispatch_due_tracks only ever queries `state == waiting`). Late acks mean an
    # unfinished task's message stays on the broker until it either completes or the
    # visibility timeout below elapses, at which point Redis (as the broker) redelivers it.
    # 3600s comfortably exceeds any real download+convert duration. task_reject_on_worker_lost
    # ensures a killed (not just disconnected) worker's in-flight task is requeued rather than
    # silently dropped. worker_max_tasks_per_child bounds any slow memory growth in spotdl/
    # yt-dlp's own process over a multi-week uptime by recycling the prefork child periodically.
    # See beat.py's stale-track reclaim sweep for the independent DB-level safety net covering
    # cases this redelivery mechanism doesn't (e.g. a message already acked by a pre-this-fix
    # worker, or the broker itself losing state).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 3600},
    worker_max_tasks_per_child=50,
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
