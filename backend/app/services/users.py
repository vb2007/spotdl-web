"""User identity (v17) -- ALLOWED_EMAILS decides who may log in at all; this module
turns a successful login into the `users` row that decides what they own and may do.
Same get-or-create shape as app/services/app_settings.get_output_settings.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_or_create_user(db: Session, email: str) -> User:
    """Creates the user row on first login, or loads and reconciles it on every
    later one. `is_admin` is never a one-time decision at creation -- it's
    re-derived from ADMIN_EMAIL on every call, so changing that env var takes effect
    on the next login rather than needing manual SQL. Whichever row that makes admin,
    every *other* row with is_admin=True is demoted in the same call: reconciling
    only the logging-in user would leave a previous admin privileged indefinitely
    just because they haven't logged in since ADMIN_EMAIL changed."""
    normalized = normalize_email(email)
    is_admin = normalized == normalize_email(get_settings().admin_email)
    now = datetime.now(timezone.utc)

    user = db.query(User).filter(User.email == normalized).one_or_none()
    if user is None:
        user = User(email=normalized, is_admin=is_admin, last_login_at=now)
        db.add(user)
    else:
        user.is_admin = is_admin
        user.last_login_at = now
    db.flush()

    if is_admin:
        db.query(User).filter(User.id != user.id, User.is_admin.is_(True)).update(
            {"is_admin": False}
        )
        db.flush()

    return user
