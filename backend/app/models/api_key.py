import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApiKey(Base):
    """A per-user API key (v53), the browser extension's fallback when the session cookie
    doesn't reach the API. A key authenticates as its user on exactly three routes, job create,
    reading one of its own jobs and `GET /api/auth/me` (`routers/auth.py`'s
    `require_session_or_api_key`), and never
    satisfies `require_session` or `require_admin`, even when its user is an admin.

    The secret is never stored: `hash` is the SHA-256 of the full `sdw_<prefix>_<secret>`
    string, shown once on creation (services/api_keys.py). `prefix` is kept for display only.
    Revoking sets `revoked_at` rather than deleting the row, so the list can't resurrect a
    key and a revoked key answers 401 like an unknown one."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
