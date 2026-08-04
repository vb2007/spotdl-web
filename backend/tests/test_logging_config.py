"""Structured JSON logging (v12). The one contract that matters most here: a
credentialed proxy URL must never survive into an emitted log line, by any route —
message, %-args, or a formatted exception — mirroring the v07 gotcha that already governs
app/services/proxies.py's redact() at its one call site. This is the independent,
belt-and-braces layer covering every *other* route a credentialed URL could reach a log
record through."""

import json
import logging

from app import logging_config


def _format(record: logging.LogRecord) -> dict:
    formatter = logging_config.JsonFormatter()
    return json.loads(formatter.format(record))


def _make_record(msg, args=(), exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="app.tasks.download",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


def test_plain_message_passes_through_unchanged():
    record = _make_record("download_track: track %s failed", ("abc123",))
    data = _format(record)
    assert data["message"] == "download_track: track abc123 failed"
    assert data["level"] == "ERROR"
    assert data["logger"] == "app.tasks.download"


def test_credentialed_url_in_message_is_redacted():
    record = _make_record(
        "download_track: attempting via proxy http://user:hunter2@203.0.113.5:8080"
    )
    data = _format(record)
    assert "hunter2" not in data["message"]
    assert "user" not in data["message"]
    assert "http://[redacted]@203.0.113.5:8080" in data["message"]


def test_credentialed_url_in_exception_traceback_is_redacted():
    try:
        raise RuntimeError(
            "Invalid proxy server: http://baduser:badpass@198.51.100.9:3128"
        )
    except RuntimeError:
        import sys

        record = _make_record("download_track: track failed", exc_info=sys.exc_info())

    data = _format(record)
    assert "badpass" not in data["exc_info"]
    assert "baduser" not in data["exc_info"]
    assert "[redacted]" in data["exc_info"]


def test_no_task_context_outside_a_running_task():
    record = _make_record("plain log line, no celery task running")
    data = _format(record)
    assert "task_id" not in data
    assert "task_name" not in data


def test_task_context_injected_when_running_inside_a_task(monkeypatch):
    class _FakeRequest:
        id = "11111111-1111-1111-1111-111111111111"

    class _FakeTask:
        name = "app.tasks.download.download_track"
        request = _FakeRequest()

    monkeypatch.setattr(logging_config, "current_task", _FakeTask())

    record = _make_record("download_track: track %s failed", ("abc123",))
    data = _format(record)
    assert data["task_id"] == "11111111-1111-1111-1111-111111111111"
    assert data["task_name"] == "app.tasks.download.download_track"
