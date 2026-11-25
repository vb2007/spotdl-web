"""User identity (v17) -- the allowlist decides who may log in at all (v69: the
`allowed_emails` table, services/allowlist.py; before it the ALLOWED_EMAILS env list); this
module turns a successful login into the `users` row that decides what they own and may do.
Same get-or-create shape as app/services/app_settings.get_output_settings.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_or_create_user(
    db: Session, email: str, username: str | None = None, is_superuser: bool | None = None
) -> User:
    """Creates the user row on first login, or loads and reconciles it on every later one.

    `is_admin` (v72) follows the upstream: `is_superuser` from this login's `GET /user` sets it
    when known (True grants, False revokes), and None (a failed or odd read) never changes it,
    so a new row starts non-admin. The dev override (`ADMIN_EMAIL`, honored only under
    SPOTDL_ENV=dev, config.py) wins over both: that row is admin, and every *other* admin row
    is demoted in the same call, so changing the override takes effect on the next login
    (v17). The upstream path demotes nobody else: only a read of their own may change a flag.

    `username` (v25) is only overwritten when a fresh, truthy value came back from this login's
    `GET /user`: a failed fetch (None) or an empty string never erases a known-good one."""
    normalized = normalize_email(email)
    dev_admin = normalize_email(get_settings().admin_email)
    is_dev_admin = bool(dev_admin) and normalized == dev_admin
    is_admin = True if is_dev_admin else is_superuser
    now = datetime.now(timezone.utc)

    user = db.query(User).filter(User.email == normalized).one_or_none()
    if user is None:
        user = User(email=normalized, username=username or None, is_admin=bool(is_admin), last_login_at=now)
        db.add(user)
    else:
        if is_admin is not None:
            user.is_admin = is_admin
        user.last_login_at = now
        if username:
            user.username = username
    db.flush()

    if is_dev_admin:
        db.query(User).filter(User.id != user.id, User.is_admin.is_(True)).update(
            {"is_admin": False}
        )
        db.flush()

    return user
