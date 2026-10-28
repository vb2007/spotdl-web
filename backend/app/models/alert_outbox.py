import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AlertState(str, enum.Enum):
    # Waiting for its first send, or backing off after a failed one (next_attempt_at).
    PENDING = "pending"
    SENT = "sent"
    # Gave up: still unsent ALERT_GIVE_UP_AFTER (24h) after it was raised.
    FAILED = "failed"
    # Never sent, by decision: the cooldown, or the category switched off (last_error says).
    SUPPRESSED = "suppressed"


class AlertOutbox(Base):
    """One row per alert raised (v59), the durable record of what was said to the Matrix
    room, what is still to be said, and what was held back. services/alerts.py's `record`
    inserts it (deciding the cooldown there, so a suppressed alert is a row too), and its
    `deliver_due` sends due rows with backoff: from beat's `deliver_alerts` tick and from the
    alert watchdog, since beat is one of the things alerted on. Postgres is the source of
    truth here as it is for `tracks.scheduled_at`: before v59 an alert was a fire-and-forget
    Celery message that a backlog, a restart or one failed request lost without a trace.

    The row id doubles as the Matrix transaction id, so a retry of a send whose answer was lost
    can't post twice. Rows are pruned 30 days after they're raised (ALERT_RETENTION)."""

    __tablename__ = "alert_outbox"
    __table_args__ = (
        # The cooldown lookup (same category + fingerprint, newest first).
        Index("ix_alert_outbox_category_fingerprint", "category", "fingerprint", "created_at"),
        # The delivery pass reads only pending rows, oldest first.
        Index(
            "ix_alert_outbox_pending",
            "created_at",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    # Exactly what reaches the room: labelled, redacted and capped (alerts.format_body).
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # History and the prune read it newest first / by age (the panel's paging key).
    created_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    state: Mapped[AlertState] = mapped_column(
        Enum(AlertState, name="alert_state", values_callable=lambda cls: [e.value for e in cls]),
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Pending rows only: when the next send may start (a claimed row holds it a lease ahead).
    next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # The last failed send's reason (redacted), or why the row was suppressed.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
