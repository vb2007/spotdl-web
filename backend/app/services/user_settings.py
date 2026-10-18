"""Per-user preferences: retention (v19) and keyboard shortcuts (v45) -- get-or-create singleton row per user, the same
pattern as app/services/app_settings.py's output-settings row, just keyed by `user_id`
instead of a fixed `id=1`.
"""

from sqlalchemy.orm import Session

from app.models import UserSettings


def get_user_settings(db: Session, user_id) -> UserSettings:
    row = db.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        db.add(row)
        db.flush()
    return row


def update_retention(db: Session, user_id, retention_days: int | None) -> UserSettings:
    row = get_user_settings(db, user_id)
    row.retention_days = retention_days
    return row


def keyboard_shortcuts_enabled(db: Session, user_id) -> bool:
    """Read-only: a user with no settings row yet has the default (on), and no row is
    created for asking, so `/api/auth/me` stays a pure read."""
    row = db.get(UserSettings, user_id)
    return True if row is None else row.keyboard_shortcuts


def update_keyboard_shortcuts(db: Session, user_id, enabled: bool) -> UserSettings:
    row = get_user_settings(db, user_id)
    row.keyboard_shortcuts = enabled
    return row
