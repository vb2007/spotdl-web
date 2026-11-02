"""The login allowlist, managed by the admin (v69): `/users` reads and edits it here.

Admin only, by v56's A6 rule: the list and the add name no id, so a non-admin gets 403
`admin_required`; the remove names an address, so it answers a non-admin 404, exactly like a
route that doesn't exist (`require_admin_hidden`). All three need the cookie session: an API key
never reaches `require_session` (v53), an admin's key included.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.routers.auth import require_admin, require_admin_hidden
from app.services import allowlist

router = APIRouter(prefix="/api/admin/allowlist", tags=["admin"])


class AllowlistAdd(BaseModel):
    email: str


@router.get("")
def list_allowlist(_admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return {"items": allowlist.list_rows(db)}


@router.post("", status_code=201)
def add_to_allowlist(
    payload: AllowlistAdd, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    addition = allowlist.add(db, payload.email, admin)
    return {**allowlist.get_row(db, addition.row.email), "resumed_jobs": len(addition.resumed_job_ids)}


@router.delete("/{email}", status_code=204)
def remove_from_allowlist(
    email: str, _admin: User = Depends(require_admin_hidden), db: Session = Depends(get_db)
) -> Response:
    allowlist.remove(db, email)
    return Response(status_code=204)
