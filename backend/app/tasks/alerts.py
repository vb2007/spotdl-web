import logging

from app.db import SessionLocal
from app.services import alerts, app_settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Used only if app_settings can't be read -- the same value as the column's default.
_FALLBACK_COOLDOWN_SECONDS = 60 * 60


@celery_app.task(name="app.tasks.alerts.send_alert", ignore_result=True)
def send_alert(category: str, fingerprint: str, text: str) -> None:
    """v36: the one place an enqueued alert is actually sent (worker-meta, `meta` queue).
    Never retried and never raises: alerts.deliver logs a failure once and drops it."""
    if category == alerts.CATEGORY_BREAKER and fingerprint.startswith("trip:"):
        # Recorded even with the breaker category toggled off, so turning it back on
        # mid-trip still gets the matching release.
        alerts.mark_breaker_open()

    enabled = True
    cooldown_seconds = _FALLBACK_COOLDOWN_SECONDS
    db = SessionLocal()
    try:
        row = app_settings.get_alert_settings(db)
        enabled = alerts.category_enabled(row, category)
        cooldown_seconds = row.alert_cooldown_minutes * 60
        db.commit()
    except Exception:
        # An unreadable settings row shouldn't swallow the alert that may be about it.
        logger.exception("alerts: could not read alert settings; sending with defaults")
        db.rollback()
    finally:
        db.close()

    if not enabled:
        logger.info("alerts: %s alert not sent, category is off in settings", category)
        return
    alerts.deliver(category, fingerprint, text, cooldown_seconds)
