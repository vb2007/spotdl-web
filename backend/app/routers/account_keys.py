"""`/api/account/api-keys` (v53): a user's own API keys, for the browser extension.

Cookie session only (`require_session`): a key can't list, mint or revoke keys, its own
included. Every query is scoped to the caller, and another user's key id answers 404 exactly
like an unknown one, admins included (a key is a credential, not data an admin manages).
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.routers.auth import require_session
from app.services import api_keys

router = APIRouter(prefix="/api/account/api-keys", tags=["account"])


class CreateApiKeyRequest(BaseModel):
    label: str


@router.get("")
def list_api_keys(db: Session = Depends(get_db), user: User = Depends(require_session)) -> dict:
    return {
        "keys": [api_keys.key_to_dict(key) for key in api_keys.active_keys(db, user.id)],
        "max_active": api_keys.MAX_ACTIVE_KEYS,
    }


@router.post("", status_code=201)
def create_api_key(
    payload: CreateApiKeyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    try:
        label = api_keys.normalize_label(payload.label)
    except api_keys.LabelInvalid as exc:
        detail = (
            f"A key needs a label of 1 to {api_keys.LABEL_MAX_LENGTH} characters"
            if exc.reason == "length"
            else "A label can't hold invisible or control characters"
        )
        raise ApiError(
            422,
            "api_key_label_invalid",
            detail,
            {"max": api_keys.LABEL_MAX_LENGTH, "reason": exc.reason},
        ) from None
    try:
        key, raw_key = api_keys.create_key(db, user.id, label)
    except api_keys.ApiKeyLimitReached:
        raise ApiError(
            409,
            "api_key_limit_reached",
            f"At most {api_keys.MAX_ACTIVE_KEYS} active keys; revoke one first",
            {"max": api_keys.MAX_ACTIVE_KEYS},
        ) from None
    db.commit()
    # The only time the key exists outside the caller's hands.
    return {**api_keys.key_to_dict(key), "key": raw_key}


@router.delete("/{key_id}")
def revoke_api_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    key = api_keys.revoke_key(db, user.id, key_id)
    if key is None:
        raise ApiError(404, "api_key_not_found", "API key not found")
    db.commit()
    return api_keys.key_to_dict(key)
