"""Per-user preferences: retention (v19), keyboard shortcuts (v45), language and clock (v46), job
notifications (v66) -- get-or-create singleton row per user, the same
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


def language_preference(db: Session, user_id) -> str | None:
    """Read-only, like `keyboard_shortcuts_enabled`: no row (or no choice yet) is `None`."""
    row = db.get(UserSettings, user_id)
    return None if row is None else row.language


def update_language(db: Session, user_id, language: str | None) -> UserSettings:
    row = get_user_settings(db, user_id)
    row.language = language
    return row


def clock_preference(db: Session, user_id) -> str | None:
    """Read-only, like `language_preference`: no row (or automatic) is `None`."""
    row = db.get(UserSettings, user_id)
    return None if row is None else row.clock


def update_clock(db: Session, user_id, clock: str | None) -> UserSettings:
    row = get_user_settings(db, user_id)
    row.clock = clock
    return row


def job_notifications_enabled(db: Session, user_id) -> bool:
    """Read-only, like `keyboard_shortcuts_enabled`: no row is the default (off)."""
    row = db.get(UserSettings, user_id)
    return False if row is None else row.job_notifications


def update_job_notifications(db: Session, user_id, enabled: bool) -> UserSettings:
    row = get_user_settings(db, user_id)
    row.job_notifications = enabled
    return row
