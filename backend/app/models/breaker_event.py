import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BreakerEventKind(str, enum.Enum):
    TRIPPED = "tripped"
    # A trip while the escalation count is still up (no success since the last trip): the
    # next, longer step of BREAKER_TRIP_DELAYS. Same verb split as v36's breaker alert.
    ESCALATED = "escalated"
    RELEASED = "released"


class BreakerEvent(Base):
    """One row per circuit-breaker transition (v44), the history behind the admin stats
    page's breaker chart. worker_state only ever holds the *current* breaker; this is
    append-only and never pruned (a trip is at least 30m long, so even a breaker that
    trips back to back writes a few dozen rows a day).

    Trips are written at retry.maybe_trip_breaker, the same point v36's alert is queued
    from, in the same transaction. Releases are written by retry.record_breaker_release:
    a manual release (the admin's button, at that moment) or the pause running out (noticed
    by beat's dispatch tick, stamped with the pause's own end time)."""

    __tablename__ = "breaker_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[BreakerEventKind] = mapped_column(
        Enum(
            BreakerEventKind,
            name="breaker_event_kind",
            values_callable=lambda cls: [e.value for e in cls],
        ),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    # Trips only: the pause this step imposed (BREAKER_TRIP_DELAYS), the escalation count it
    # reached, and when that pause was due to end.
    step_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trip_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paused_until: Mapped[datetime | None] = mapped_column(nullable=True)
    # Releases only: true for the admin's manual release, false for a pause that ran out.
    manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
