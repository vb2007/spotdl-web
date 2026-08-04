"""Structured JSON logging (v12) — one shared formatter both uvicorn (`api`, via
`logging.json` + `--log-config`) and every Celery process (`worker-dl`/`worker-meta`/
`beat`, via the `setup_logging` signal below) route through, so `docker compose logs
<service>` is greppable/parseable by track id, task name, and error type across all four
backend processes instead of being five differently-shaped plain-text streams.
"""

import logging
import re

from celery import current_task
from celery.signals import setup_logging
from pythonjsonlogger.json import JsonFormatter as _BaseJsonFormatter

# Matches `user:pass@` inside any URL-shaped string. Belt-and-braces on top of
# app/services/proxies.py's redact() — that's only reliably applied at the one call site
# in download.py that already knows a proxy was involved. This catches any *other* route a
# credentialed proxy URL could reach a log record through (a raw exception message from a
# library we don't control, a stray `extra=` field, etc.) before it reaches an emitted
# JSON line. See CLAUDE.md's v07 proxy-redaction gotcha — this is the same contract,
# enforced one layer further out as a safety net, not a replacement for the call-site fix.
_CREDENTIALED_URL = re.compile(r"://[^/@\s]+:[^/@\s]+@")


def _redact(text: str) -> str:
    return _CREDENTIALED_URL.sub("://[redacted]@", text)


class JsonFormatter(_BaseJsonFormatter):
    """Adds Celery task context (`task_id`/`task_name`) when a log call happens inside a
    task, and redacts credentialed URLs from both the message and any formatted
    exception. Used by both the Celery `setup_logging` receiver below and uvicorn's
    `--log-config logging.json` (see that file's `"()"` factory reference to this class)."""

    def add_fields(self, log_data, record, message_dict):
        super().add_fields(log_data, record, message_dict)
        log_data["level"] = record.levelname
        log_data["logger"] = record.name

        task = current_task
        if task is not None and getattr(task, "request", None) is not None and task.request.id:
            log_data["task_id"] = task.request.id
            log_data["task_name"] = task.name

        if "message" in log_data and isinstance(log_data["message"], str):
            log_data["message"] = _redact(log_data["message"])
        if log_data.get("exc_info"):
            log_data["exc_info"] = _redact(log_data["exc_info"])


@setup_logging.connect
def _configure_celery_logging(**kwargs) -> None:
    """Connecting *any* receiver to this signal tells Celery to skip its own logging
    setup entirely — deliberate, not a side effect to work around (see Celery's docs on
    `setup_logging`). This makes this function the one place responsible for the root
    logger's handler/formatter in every Celery process (worker-dl, worker-meta, beat).
    `-l info` in docker-compose.yml's `command`s becomes documentation only once this is
    connected; the actual level is set here. Registered as a module-level decorator so it
    connects as soon as anything imports this module — app/tasks/celery_app.py does so
    unconditionally, which is early enough to run before Celery's own bootstep would
    otherwise configure logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
