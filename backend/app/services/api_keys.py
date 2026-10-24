"""Per-user API keys (v53): the browser extension's fallback when the session cookie doesn't
reach the API.

A key is `sdw_<prefix>_<secret>`: `prefix` is 8 random hex characters kept for display, and
`secret` is 32 random bytes, URL-safe base64. Only the SHA-256 of the whole string is stored
(`api_keys.hash`), so the key is shown exactly once, in the create response, and a database
read never yields a usable key. Lookup is by that hash; a revoked key matches nothing.

What a key may do is decided in `routers/auth.py`, not here: it authenticates as its user on
job create, `GET /api/jobs/{id}` (its own jobs) and `GET /api/auth/me` only.
"""

import hashlib
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ApiKey, User

KEY_PREFIX = "sdw_"
# A user's active (unrevoked) keys. One per browser profile is the expected use; ten leaves
# room for a few devices without letting keys pile up unreviewed.
MAX_ACTIVE_KEYS = 10
LABEL_MAX_LENGTH = 64
# `last_used_at` is a hint for the /account list, not an audit log: at most one write a
# minute per key, never one per request.
LAST_USED_RESOLUTION = timedelta(minutes=1)


class ApiKeyLimitReached(Exception):
    pass


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _generate() -> tuple[str, str]:
    """A fresh `(prefix, raw_key)`."""
    prefix = secrets.token_hex(4)
    return prefix, f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"


# Kept inside a label although they're format characters: emoji sequences need them.
_JOINERS = {"\u200c", "\u200d"}
# Tag characters, allowed only inside a subdivision flag (🏴 + tags, ending in U+E007F).
_BLACK_FLAG = "\U0001f3f4"
_TAGS = range(0xE0020, 0xE0080)


def _unfit_at(label: str, index: int) -> bool:
    """Whether label[index] is a character a label must not hold, by Unicode category:
    controls (a NUL can't be stored in Postgres text at all), lone surrogates (can't be
    encoded to UTF-8), format characters (bidi controls and marks, zero-width spaces: they
    reorder the key's prefix around them or make two labels look alike) and line/paragraph
    separators. Kept: ZWJ/ZWNJ (emoji sequences), tag characters inside a subdivision flag,
    and unassigned or private-use code points (Python's Unicode tables trail new emoji, and
    macOS types the Apple logo as private use)."""
    char = label[index]
    if char in _JOINERS:
        return False
    if ord(char) in _TAGS:
        start = index
        while start > 0 and ord(label[start - 1]) in _TAGS:
            start -= 1
        return not (start > 0 and label[start - 1] == _BLACK_FLAG)
    return unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}


# Characters that show as blank although Unicode calls them letters or symbols.
_FILLERS = {"\u115f", "\u1160", "\u3164", "\uffa0", "\u2800"}


def _visible(label: str) -> bool:
    """At least one character that shows: not only marks, fillers and joiners."""
    return any(
        unicodedata.category(c)[0] in "LNPS" and c not in _FILLERS for c in label
    )


class LabelInvalid(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # "length" or "character"


def normalize_label(label: str) -> str:
    """The label as stored. Raises LabelInvalid("length") when it's empty or too long once
    trimmed, LabelInvalid("character") when it holds a character a label can't, or nothing
    visible."""
    # Only plain spaces are trimmed silently: `str.strip()` also eats \x1c-\x1f and U+0085,
    # which would report a control character as an empty name.
    label = label.strip(" ")
    if not label or len(label) > LABEL_MAX_LENGTH:
        raise LabelInvalid("length")
    if any(_unfit_at(label, i) for i in range(len(label))) or not _visible(label):
        raise LabelInvalid("character")
    return label


def active_keys(db: Session, user_id: uuid.UUID) -> list[ApiKey]:
    return (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc(), ApiKey.id)
        .all()
    )


def create_key(db: Session, user_id: uuid.UUID, label: str) -> tuple[ApiKey, str]:
    """Creates a key for `user_id` and returns it with the raw key, which exists only in this
    return value. `label` must already be normalized. Raises ApiKeyLimitReached at
    MAX_ACTIVE_KEYS active keys. The caller commits."""
    # Two creates at once would both count below the limit: the user's row serializes them
    # (Postgres; SQLite, the unit tests', has one writer anyway).
    db.query(User.id).filter(User.id == user_id).with_for_update(key_share=True).one()
    active = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .count()
    )
    if active >= MAX_ACTIVE_KEYS:
        raise ApiKeyLimitReached
    prefix, raw_key = _generate()
    key = ApiKey(user_id=user_id, label=label, prefix=prefix, hash=_hash(raw_key))
    db.add(key)
    db.flush()
    return key, raw_key


def revoke_key(db: Session, user_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
    """Revokes `user_id`'s own active key `key_id`. None when there's no such key for this
    user (another user's key included: the caller answers 404 either way). The caller
    commits."""
    key = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .one_or_none()
    )
    if key is None:
        return None
    key.revoked_at = datetime.now(timezone.utc)
    db.flush()
    return key


def looks_like_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX)


def authenticate(db: Session, raw_key: str) -> ApiKey | None:
    """The active key `raw_key` names, or None. Touches `last_used_at` at most once per
    LAST_USED_RESOLUTION (flushed, not committed: the caller commits)."""
    if not looks_like_key(raw_key):
        return None
    key = (
        db.query(ApiKey)
        .filter(ApiKey.hash == _hash(raw_key), ApiKey.revoked_at.is_(None))
        .one_or_none()
    )
    if key is None:
        return None
    now = datetime.now(timezone.utc)
    last_used_at = key.last_used_at
    if last_used_at is not None and last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)
    if last_used_at is None or now - last_used_at >= LAST_USED_RESOLUTION:
        key.last_used_at = now
        db.flush()
    return key


def key_to_dict(key: ApiKey) -> dict:
    return {
        "id": str(key.id),
        "label": key.label,
        "prefix": key.prefix,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }
