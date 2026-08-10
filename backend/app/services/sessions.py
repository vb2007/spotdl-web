import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import UserSession

# Idle timeout, not a Postgres TTL — enforced here so it stays explicit and testable (v03 plan).
SESSION_IDLE_TIMEOUT = timedelta(days=30)


def create_session(db: Session, user_id: uuid.UUID) -> UserSession:
    session = UserSession(user_id=user_id, token=secrets.token_hex(32))
    db.add(session)
    db.flush()
    return session


def get_valid_session(db: Session, token: str) -> UserSession | None:
    session = db.query(UserSession).filter(UserSession.token == token).one_or_none()
    if session is None:
        return None

    last_seen_at = session.last_seen_at
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) - last_seen_at > SESSION_IDLE_TIMEOUT:
        db.delete(session)
        db.flush()
        return None

    session.last_seen_at = datetime.now(timezone.utc)
    db.flush()
    return session


def delete_session(db: Session, token: str) -> None:
    db.query(UserSession).filter(UserSession.token == token).delete()
