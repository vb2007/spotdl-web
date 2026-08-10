import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserSession(Base):
    """Our own session store — separate from the upstream VB-AUTH token (see v03).

    Named `UserSession`, not `Session` (v02's naming gotcha: `sqlalchemy.orm.Session` is
    dep-injected everywhere, so a model named `Session` would force an import alias at
    every call site)."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
