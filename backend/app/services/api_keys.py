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
import re
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


# The label rule (v53, settled over the reviews): a label is the owner's name for a key, shown
# in the /account list and the revoke dialog. It must be storable (no NUL, no lone surrogate),
# and no text in it may be invisible: an invisible character could make it render exactly like
# another key's label, or carry hidden data. So Unicode's default-ignorable characters (drawn
# as nothing) are refused, except where a script or emoji needs one, and then only in that
# context. Everything visible stays: every script, combining marks, emoji, private use (the
# macOS Apple logo), and code points newer than Python 3.12's Unicode 15.0 tables.

# Unicode's Default_Ignorable_Code_Point property (DerivedCoreProperties.txt).
_DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
    (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)
# Visible format characters (prepended number signs drawn over the digits that follow).
_VISIBLE_FORMAT = {0x0600, 0x0601, 0x0602, 0x0603, 0x0604, 0x0605, 0x06DD, 0x070F, 0x0890,
                   0x0891, 0x08E2, 0x110BD, 0x110CD}
# Letters and symbols that draw as blank.
_BLANK = {0x2800, 0x1D159, 0x16FE4}
# The three subdivision flags Unicode recommends (England, Scotland, Wales): the only place tag
# characters may appear. Each counts as one visible character.
_SUBDIVISION_FLAG = re.compile(
    "\U0001f3f4(?:"
    + "|".join("".join(chr(0xE0000 + ord(c)) for c in code) for code in ("gbeng", "gbsct", "gbwls"))
    + ")\U000e007f"
)
_FLAG_PLACEHOLDER = "\U0001f3f4"
_JOINERS = (0x200C, 0x200D)
_EMOJI_SELECTORS = (0xFE0E, 0xFE0F)
_KEYCAP_BASES = set("0123456789#*")


def _ignorable(code: int) -> bool:
    return any(low <= code <= high for low, high in _DEFAULT_IGNORABLE)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x3FFFF


def _is_mongolian(char: str) -> bool:
    return 0x1820 <= ord(char) <= 0x18AA


# At most this many default-ignorables a label may hold, however placed: enough for several
# emoji sequences (👩‍❤️‍💋‍👨 needs 4), and a bound on what invisible characters could encode.
MAX_IGNORABLES = 8
# Scripts whose letters join, where a ZWNJ changes the shaping (Arabic incl. Persian, Syriac,
# N'Ko, Mongolian).
_JOINING_SCRIPTS = ((0x0600, 0x06FF), (0x0700, 0x074F), (0x0750, 0x077F), (0x07C0, 0x07FF),
                    (0x0860, 0x08FF), (0x1800, 0x18AF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))
# Emoji skin-tone modifiers, which may sit between an emoji and its ZWJ.
_SKIN_TONES = range(0x1F3FB, 0x1F400)


def _is_virama(char: str | None) -> bool:
    return char is not None and unicodedata.combining(char) == 9


def _joining_letter(char: str | None) -> bool:
    if char is None or not unicodedata.category(char).startswith("L"):
        return False
    return any(low <= ord(char) <= high for low, high in _JOINING_SCRIPTS)


def _emoji_like(char: str | None) -> bool:
    """A pictographic symbol a ZWJ sequence can join (or a code point newer than Python's
    tables, which is where new emoji land)."""
    if char is None or ord(char) < 0x2000:
        return False
    return unicodedata.category(char) in ("So", "Sm", "Sk", "Cn")


def _allowed_ignorable(text: str, index: int) -> bool:
    """Whether the default-ignorable at text[index] is one a script or emoji needs here."""
    code = ord(text[index])
    before = text[index - 1] if index > 0 else None
    after = text[index + 1] if index + 1 < len(text) else None
    if code in _JOINERS:
        # Indic: around a virama (conjuncts, Malayalam chillu, Bengali ya-phala).
        if _is_virama(before) or _is_virama(after):
            return True
        # Arabic-script and other joining scripts: ZWNJ between letters (marks skipped).
        if code == 0x200C:
            left = index - 1
            while left >= 0 and unicodedata.category(text[left]).startswith("M"):
                left -= 1
            return _joining_letter(text[left] if left >= 0 else None) and _joining_letter(after)
        # Emoji ZWJ sequences, past an emoji presentation selector or a skin tone.
        if before is not None and (ord(before) in _EMOJI_SELECTORS or ord(before) in _SKIN_TONES):
            before = text[index - 2] if index > 1 else None
        return _emoji_like(before) and _emoji_like(after)
    if code in _EMOJI_SELECTORS:
        # After a keycap's digit, # or * (1️⃣), or a non-ASCII symbol or punctuation an emoji
        # picker qualifies (❤️, ‼️, 〰️), or ℹ️.
        if before is None:
            return False
        if before in _KEYCAP_BASES:
            return after == "\u20e3"
        if before == "\u2139":
            return True
        return ord(before) >= 0x80 and (
            unicodedata.category(before)[0] in "SP" or unicodedata.category(before) == "Cn"
        )
    if 0xE0100 <= code <= 0xE01EF:
        # An ideographic variation selector, after a CJK ideograph (Japanese name variants).
        return before is not None and _is_cjk(before)
    if 0x180B <= code <= 0x180F:
        # Mongolian variation selectors and vowel separator, within Mongolian text.
        return before is not None and _is_mongolian(before)
    return False


def _collapse_spaces(label: str) -> str:
    """Space separators off both ends, and each run inside down to one plain space: two spaces,
    or an NBSP, would otherwise look exactly like one. Not `str.strip()`, which also eats
    \\x1c-\\x1f and U+0085 and would report a control character as an empty name."""
    out: list[str] = []
    for char in label:
        if unicodedata.category(char) == "Zs":
            if out and out[-1] != " ":
                out.append(" ")
        else:
            out.append(char)
    return "".join(out).rstrip(" ")


class LabelInvalid(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # "length" or "character"


def normalize_label(label: str) -> str:
    """The label as stored (space separators collapsed, see `_collapse_spaces`). Raises
    LabelInvalid("length") when it's empty or longer than LABEL_MAX_LENGTH code points,
    LabelInvalid("character") when it holds a character a label can't, or nothing visible."""
    label = _collapse_spaces(label)
    if not label or len(label) > LABEL_MAX_LENGTH:
        raise LabelInvalid("length")
    text = _SUBDIVISION_FLAG.sub(_FLAG_PLACEHOLDER, label)
    visible = ignorables = 0
    for index, char in enumerate(text):
        code = ord(char)
        category = unicodedata.category(char)
        if category in ("Cc", "Cs", "Zl", "Zp") or code in _BLANK:
            raise LabelInvalid("character")
        if _ignorable(code):
            ignorables += 1
            if ignorables > MAX_IGNORABLES or not _allowed_ignorable(text, index):
                raise LabelInvalid("character")
            continue
        if category == "Cf" and code not in _VISIBLE_FORMAT:
            raise LabelInvalid("character")
        if category[0] in "LNPS" or category in ("Cn", "Co", "Cf"):
            visible += 1
    if not visible:
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
    # Two creates at once would both count below the limit: the user's row serializes them.
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
