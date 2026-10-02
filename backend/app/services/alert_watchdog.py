"""Entry point of the v36 alert watchdog process: `python -m app.services.alert_watchdog`,
started by alerts.start_watchdog() from worker-meta (see alerts.Watchdog for why it's a
separate process). Lives with its parent: it exits when worker-meta's main process does."""

import logging
import os
import threading
import time

from app.logging_config import _configure_celery_logging
from app.services.alerts import WATCHDOG_INTERVAL_SECONDS, Watchdog

logger = logging.getLogger("app.services.alerts")


def _exit_with_parent(parent_pid: int) -> None:
    # Reparented (to PID 1 or a subreaper) means worker-meta is gone -- never outlive it.
    while os.getppid() == parent_pid:
        time.sleep(5)
    os._exit(0)


def main() -> None:
    # A fresh interpreter has no logging config -- same JSON formatter as every Celery
    # process (app/logging_config.py).
    _configure_celery_logging()
    threading.Thread(target=_exit_with_parent, args=(os.getppid(),), daemon=True).start()
    logger.info(
        "alerts: watchdog started (pid %s, every %ss)", os.getpid(), WATCHDOG_INTERVAL_SECONDS
    )
    Watchdog().run()


if __name__ == "__main__":
    main()
