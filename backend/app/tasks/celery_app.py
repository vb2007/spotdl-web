import os

from celery import Celery, bootsteps
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
    task_queues=(Queue("meta"), Queue("downloads"), Queue("expand")),
    # v34.1: the two tasks that legitimately run for minutes -- URL expansion (a whole
    # artist discography is ~90-130s of Spotify round trips, measured) and the admin
    # library sweep -- get their own queue and worker (`worker-expand`). On the shared
    # 2-slot `meta` queue, two concurrent discographies held both slots and beat's 30s
    # dispatch-due-tracks ticks sat `received` until one finished: no downloads were
    # dispatched (and no stale sweep ran) for the whole expansion.
    task_routes={
        "app.tasks.download.*": {"queue": "downloads"},
        "app.tasks.expand.*": {"queue": "expand"},
        "app.tasks.library.*": {"queue": "expand"},
    },
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-tracks": {
            "task": "app.tasks.beat.dispatch_due_tracks",
            "schedule": 30.0,
        },
        # Hourly, not 30s -- archiving is housekeeping, not latency-sensitive, and it
        # competes with dispatch-due-tracks for the same worker-meta process.
        "archive-due-jobs": {
            "task": "app.tasks.beat.archive_due_jobs",
            "schedule": 3600.0,
        },
    },
    # Durability (v12): with the default task_acks_late=False, a track's broker message is
    # acked *before* download_track's body runs — a `docker compose down`/OOM-kill/host
    # crash mid-download loses that message entirely, stranding the track in `downloading`
    # forever (dispatch_due_tracks only ever queries `state == waiting`). Late acks mean an
    # unfinished task's message stays on the broker until it either completes or the
    # visibility timeout below elapses, at which point Redis (as the broker) redelivers it.
    # The timeout (6h since v34.1, see below) exceeds any real task. task_reject_on_worker_lost
    # ensures a killed (not just disconnected) worker's in-flight task is requeued rather than
    # silently dropped. worker_max_tasks_per_child bounds any slow memory growth in spotdl/
    # yt-dlp's own process over a multi-week uptime by recycling the prefork child periodically.
    # See beat.py's stale-track reclaim sweep for the independent DB-level safety net covering
    # cases this redelivery mechanism doesn't (e.g. a message already acked by a pre-this-fix
    # worker, or the broker itself losing state).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 6h, not Celery's 1h (v34.1): with acks_late, a task still running when this expires
    # is redelivered and runs a *second* time concurrently -- for an expansion, that's
    # every track inserted twice. A huge discography or a library sweep can approach 1h;
    # 6h can't. The cost: a task lost to a hard crash of the whole worker (a child-only
    # crash is requeued at once by task_reject_on_worker_lost) is redelivered up to 6h
    # later. Downloads are covered sooner by beat's DB-driven stale-track sweep; a lost
    # expansion stays `expanding` (or a library sweep `running`) until then -- the
    # owner-accepted trade (v34.1).
    broker_transport_options={"visibility_timeout": 21600},
    worker_max_tasks_per_child=50,
)

# Importing task modules here (after celery_app is defined) registers their @celery_app.task
# decorators with this app — required since the worker command doesn't pass --include.
from app.tasks import download  # noqa: E402,F401
from app.tasks import expand  # noqa: E402,F401
from app.tasks import beat  # noqa: E402,F401
from app.tasks import library  # noqa: E402,F401
from app.tasks import alerts  # noqa: E402,F401


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


class AlertWatchdogStep(bootsteps.StartStopStep):
    """v36: same explicit-env-var-gate convention -- the alert watchdog (beat heartbeat,
    breaker release, failure spike) runs alongside worker-meta only, as its own child
    process rather than a beat-scheduled task, since beat is one of the things it watches
    (see alerts.Watchdog). This step also supervises it: the worker's own timer (main
    thread, no extra thread in this forking process) polls it every interval and respawns
    it if it died, so an OOM-killed watchdog doesn't silently end every watchdog alert.
    Also where "alerts are on/off" is logged at startup."""

    requires = {"celery.worker.components:Timer"}

    def __init__(self, worker, **kwargs):
        self.process = None
        self.tref = None

    def include_if(self, worker):
        return os.environ.get("RUN_ALERT_WATCHDOG") == "true"

    def start(self, worker):
        from app.services import alerts

        alerts.log_startup_state()
        if not alerts.is_configured():
            return
        self._spawn()
        self.tref = worker.timer.call_repeatedly(alerts.WATCHDOG_INTERVAL_SECONDS, self._supervise)

    def _spawn(self):
        # Never fatal: a failed spawn (ENOMEM/EAGAIN in a size-capped container) must not
        # crash-loop worker-meta, which runs beat's dispatch. The next tick retries.
        from app.services import alerts

        try:
            self.process = alerts.spawn_watchdog()
        except OSError as exc:
            self.process = None
            alerts.logger.warning(
                "alerts: could not start the watchdog (%s); retrying next interval",
                type(exc).__name__,
            )

    def _supervise(self):
        from app.services import alerts

        if self.process is None:
            self._spawn()
            return
        code = self.process.poll()
        if code is not None:
            alerts.logger.warning("alerts: watchdog exited (code %s); restarting it", code)
            self._spawn()

    def stop(self, worker):
        if self.tref is not None:
            self.tref.cancel()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


celery_app.steps["worker"].add(AlertWatchdogStep)
