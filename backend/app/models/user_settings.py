import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserSettings(Base):
    """Per-user preferences, get-or-create on first read -- same singleton-row pattern
    as app_settings.py's get_output_settings, just keyed per user instead of a fixed
    id=1 row. Kept separate from `users` because `users` is read on every authenticated
    request while settings are read rarely and will keep growing (v19+)."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
