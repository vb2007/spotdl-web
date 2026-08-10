import json

import redis

from app.services import events


class _FakeSongTracker:
    def __init__(self, progress):
        self.progress = progress


def test_publish_track_event_minimal_shape(monkeypatch):
    captured = {}
    monkeypatch.setattr(events, "publish", lambda user_id, event: captured.update(event))

    events.publish_track_event("user-1", "track-1", "job-1", "downloading")

    assert captured == {"type": "track.state", "track_id": "track-1", "job_id": "job-1", "state": "downloading"}


def test_publish_track_event_includes_optional_fields(monkeypatch):
    captured = {}
    monkeypatch.setattr(events, "publish", lambda user_id, event: captured.update(event))

    from datetime import datetime, timezone

    scheduled_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events.publish_track_event(
        "user-1", "track-1", "job-1", "waiting", scheduled_at=scheduled_at, error="boom"
    )

    assert captured["scheduled_at"] == scheduled_at.isoformat()
    assert captured["error"] == "boom"
    assert "progress" not in captured


def test_publish_job_event_shape(monkeypatch):
    captured = {}
    monkeypatch.setattr(events, "publish", lambda user_id, event: captured.update(event))

    events.publish_job_event("user-1", "job-1", "expanded")

    assert captured == {"type": "job.state", "job_id": "job-1", "state": "expanded"}


def test_make_progress_callback_publishes_downloading_progress(monkeypatch):
    captured = {}

    def fake_publish_track_event(user_id, track_id, job_id, state, **kwargs):
        captured.update(user_id=user_id, track_id=track_id, job_id=job_id, state=state, **kwargs)

    monkeypatch.setattr(events, "publish_track_event", fake_publish_track_event)

    callback = events.make_progress_callback("user-1", "track-1", "job-1")
    callback(_FakeSongTracker(progress=42), "Downloading")

    assert captured == {
        "user_id": "user-1",
        "track_id": "track-1",
        "job_id": "job-1",
        "state": "downloading",
        "progress": 42,
    }


def test_publish_adds_timestamp_and_serializes_json(monkeypatch):
    published = []

    class _FakeClient:
        def publish(self, channel, payload):
            published.append((channel, json.loads(payload)))

    monkeypatch.setattr(events, "_get_client", lambda: _FakeClient())

    events.publish("user-1", {"type": "track.state", "state": "completed"})

    channel, payload = published[0]
    assert channel == events.channel_for("user-1")
    assert payload["type"] == "track.state"
    assert "ts" in payload


def test_publish_swallows_redis_errors(monkeypatch):
    class _FailingClient:
        def publish(self, channel, payload):
            raise redis.ConnectionError("connection refused")

    monkeypatch.setattr(events, "_get_client", lambda: _FailingClient())

    # Must not raise — a Redis hiccup can't be allowed to fail the calling task.
    events.publish("user-1", {"type": "track.state"})


def test_publish_track_event_requires_owner():
    """The whole enforcement mechanism (v17): a call site that forgets the owner fails
    loudly instead of silently broadcasting to nobody's channel."""
    try:
        events.publish_track_event("track-1", "job-1", "downloading")
    except TypeError:
        pass
    else:
        raise AssertionError("expected a TypeError for the missing owner argument")
