import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Proxy, ProxySource, User
from app.routers.auth import require_admin, require_admin_hidden
from app.services import proxies
from app.services.proxies import PROXY_URL_RE, connection_target, redact

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


class CreateProxyRequest(BaseModel):
    url: str


class UpdateProxyRequest(BaseModel):
    enabled: bool


def _proxy_to_dict(proxy: Proxy) -> dict:
    # The URL is shown redacted (scheme://host:port only) even to the authenticated
    # owner -- matches the v07 stance that a proxy's plaintext user:pass should never
    # reach logs, last_error, or (now) a screen either.
    return {
        "id": str(proxy.id),
        "url": redact(proxy.url),
        "enabled": proxy.enabled,
        "source": proxy.source.value,
        "consecutive_failures": proxy.consecutive_failures,
        "cooldown_until": proxy.cooldown_until.isoformat() if proxy.cooldown_until is not None else None,
        "last_used_at": proxy.last_used_at.isoformat() if proxy.last_used_at is not None else None,
        "last_success_at": (
            proxy.last_success_at.isoformat() if proxy.last_success_at is not None else None
        ),
        # v56 (A4): deleted while a download was using it; gone once that's done.
        "deleting": proxy.delete_requested_at is not None,
    }


def _target_clash(
    db: Session, url: str, *, exclude: Proxy | None = None, enabled_only: bool = False
) -> ApiError | None:
    """One connection target, one credential (v44, the owner's rule): two rows for one
    host:port would be the same proxy twice, told apart on /stats only by a credential
    that must never be shown. The detail names the target only, never a credential."""
    target = connection_target(url)
    for other in db.query(Proxy).all():
        # v56: a row waiting to be deleted is on its way out (never picked again).
        if other is exclude or other.delete_requested_at is not None or (enabled_only and not other.enabled):
            continue
        if connection_target(other.url) != target:
            continue
        where = "change it in proxies.txt" if other.source == ProxySource.FILE else "delete that one first"
        return ApiError(
            409,
            "proxy_target_exists",
            f"There is already a proxy for {target}. One address takes one credential: {where}.",
            {"target": target, "source": other.source.value},
        )
    return None


def _get_proxy_or_404(db: Session, proxy_id: uuid.UUID) -> Proxy:
    proxy = db.get(Proxy, proxy_id)
    if proxy is None:
        raise ApiError(404, "proxy_not_found", "Proxy not found")
    return proxy


@router.get("")
def list_proxies(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    proxies = db.query(Proxy).order_by(Proxy.source, Proxy.url).all()
    return [_proxy_to_dict(proxy) for proxy in proxies]


@router.post("", status_code=201)
def create_proxy(
    payload: CreateProxyRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Adds a source=manual proxy -- pick_proxy() draws from it exactly like a
    source=file row (see v07). Validated against spotdl's real accepted-proxy format
    (PROXY_URL_RE) -- unlike sync_from_file() (which deliberately skips this, see that
    function's own docstring), a human typing into a live form benefits from immediate
    feedback rather than a silent background failure days later."""
    url = payload.url.strip()
    if not url:
        raise ApiError(400, "proxy_url_required", "url is required")
    if not PROXY_URL_RE.match(url):
        raise ApiError(
            400,
            "proxy_url_invalid",
            "Proxy URL must look like http(s)://[user:pass@]<ipv4>[:port]",
        )

    existing = db.query(Proxy).filter(Proxy.url == url).one_or_none()
    if existing is not None:
        raise ApiError(409, "proxy_url_exists", "A proxy with this URL already exists")
    clash = _target_clash(db, url)
    if clash is not None:
        raise clash

    proxy = Proxy(url=url, source=ProxySource.MANUAL, enabled=True)
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return _proxy_to_dict(proxy)


@router.patch("/{proxy_id}")
def update_proxy(
    proxy_id: uuid.UUID,
    payload: UpdateProxyRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_hidden),
) -> dict:
    proxy = _get_proxy_or_404(db, proxy_id)
    if proxy.delete_requested_at is not None:
        raise ApiError(409, "proxy_deleting", "This proxy is being deleted")
    # A disabled row can share a target with a live one (a row from before v44, or a
    # proxies.txt line sync skipped): turning it on would run both.
    if payload.enabled and not proxy.enabled:
        clash = _target_clash(db, proxy.url, exclude=proxy, enabled_only=True)
        if clash is not None:
            raise clash
    proxy.enabled = payload.enabled
    db.commit()
    return _proxy_to_dict(proxy)


@router.delete("/{proxy_id}")
def delete_proxy(
    proxy_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_hidden),
) -> dict | None:
    """A source=manual proxy is hard-deleted -- there's no proxies.txt entry that could
    ever re-add it, so soft-disabling one (the original v13 behavior) just left a dead,
    permanently-disabled row with no way to actually get rid of it, caught in manual
    testing as a real UX dead end. A source=file row keeps the original soft delete
    (enabled=false), matching v07's never-hard-delete stance: the next sync_from_file()
    run re-enables it as long as it's still in proxies.txt, exactly like removing then
    re-adding the line, and hard-deleting it here would just lose that history for no
    reason (the file is still the real source of truth for that row).

    v56 (A4, owner's decision): a manual proxy that nothing uses is deleted at once (204).
    One a download may be using right now (`proxies.proxy_in_use`) is marked instead (202,
    `deleting: true`): it's never picked again, and `finalize_proxy_deletions` deletes it once
    that download is done. The row is locked first, so a pick (which locks its candidates)
    and this decision can't interleave."""
    proxy = _get_proxy_or_404(db, proxy_id)
    if proxy.source == ProxySource.MANUAL:
        db.refresh(proxy, with_for_update=True)
        now = datetime.now(timezone.utc)
        if not proxies.proxy_in_use(db, proxy, now):
            db.delete(proxy)
            db.commit()
            response.status_code = 204
            return None
        if proxy.delete_requested_at is None:
            proxy.delete_requested_at = now
        db.commit()
        response.status_code = 202
        return _proxy_to_dict(proxy)
    proxy.enabled = False
    db.commit()
    return _proxy_to_dict(proxy)
