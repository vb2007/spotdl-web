from datetime import datetime
import uuid

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AllowedEmail(Base):
    """Who may sign in (v69): the login allowlist, managed by the admin in `/users`.

    Imported once from `ALLOWED_EMAILS` (plus `ADMIN_EMAIL`) by the migration that created it;
    the env list is ignored after that. `ADMIN_EMAIL` itself is always allowed, row or not
    (`services.allowlist.is_allowed`), and can't be removed. The `users` table still decides
    what someone owns and may do; this one only decides who gets in.

    `email` is stored normalized (`services.users.normalize_email`). `added_by` is null for the
    imported rows and for an admin row since deleted."""

    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(Text, primary_key=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
