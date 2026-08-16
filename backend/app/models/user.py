import uuid
from datetime import datetime

from sqlalchemy import Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    """Row created on first successful login (v17). The `ALLOWED_EMAILS` env allowlist
    decides who may log in; this table decides what they own and may do -- deliberately
    separate, since one is deployment config and the other is application state."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    # Nullable (v25): a row can exist before a successful `GET /user` -- e.g. a user who
    # logged in before this column existed, or whose upstream call has never once
    # succeeded. Refreshed on every login (services.users.get_or_create_user), same
    # reconciliation pattern as is_admin, but only when a fresh value was actually
    # fetched -- a flaky upstream call must never null out a previously known-good name.
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_login_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
