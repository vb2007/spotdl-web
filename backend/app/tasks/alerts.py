import logging

from app.db import SessionLocal
from app.services import alerts
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.alerts.deliver_alerts", ignore_result=True)
def deliver_alerts() -> None:
    """v59: beat's delivery pass over the alert outbox (worker-meta, every tick). The alert
    watchdog runs the same pass after each of its checks, so a dead beat still gets its own
    alert out; the claim's lease keeps the two from sending one row twice."""
    alerts.deliver_due(SessionLocal)


@celery_app.task(name="app.tasks.alerts.prune_alert_outbox", ignore_result=True)
def prune_alert_outbox() -> None:
    """v59: hourly, keeps ALERT_RETENTION (30 days) of outbox rows."""
    db = SessionLocal()
    try:
        removed = alerts.prune_outbox(db)
        db.commit()
        if removed:
            logger.info("alerts: pruned %s outbox rows past %s", removed, alerts.ALERT_RETENTION)
    finally:
        db.close()


# acks_late=False, as before v59: a v36 message still in the broker when v59 deploys is
# recorded into the outbox (and from there delivered durably) rather than lost as an
# unregistered task. Nothing sends this task any more.
@celery_app.task(name="app.tasks.alerts.send_alert", ignore_result=True, acks_late=False)
def send_alert(category: str, fingerprint: str, text: str) -> None:
    alerts.enqueue(category, fingerprint, text)
