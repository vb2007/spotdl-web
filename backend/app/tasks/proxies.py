"""v56 (A4, owner's decision): the deferred proxy delete. An admin's delete of a manual proxy a
download is using marks it (`proxies.delete_requested_at`): it's never picked again, and this
task, every 30s on worker-meta, removes it once nothing uses it."""

import logging

from app.db import SessionLocal
from app.services import proxies
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.proxies.finalize_proxy_deletions", ignore_result=True)
def finalize_proxy_deletions() -> None:
    db = SessionLocal()
    try:
        for url in proxies.finalize_proxy_deletions(db):
            logger.info("finalize_proxy_deletions: deleted %s, no longer in use", url)
    finally:
        db.close()
