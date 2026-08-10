import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Proxy, ProxySource, User
from app.routers.auth import require_admin
from app.services.proxies import PROXY_URL_RE, redact

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
    }


def _get_proxy_or_404(db: Session, proxy_id: uuid.UUID) -> Proxy:
    proxy = db.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
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
        raise HTTPException(status_code=400, detail="url is required")
    if not PROXY_URL_RE.match(url):
        raise HTTPException(
            status_code=400,
            detail="Proxy URL must look like http(s)://[user:pass@]<ipv4>[:port]",
        )

    existing = db.query(Proxy).filter(Proxy.url == url).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A proxy with this URL already exists")

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
    _: User = Depends(require_admin),
) -> dict:
    proxy = _get_proxy_or_404(db, proxy_id)
    proxy.enabled = payload.enabled
    db.commit()
    return _proxy_to_dict(proxy)


@router.delete("/{proxy_id}")
def delete_proxy(
    proxy_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict | None:
    """A source=manual proxy is hard-deleted -- there's no proxies.txt entry that could
    ever re-add it, so soft-disabling one (the original v13 behavior) just left a dead,
    permanently-disabled row with no way to actually get rid of it, caught in manual
    testing as a real UX dead end. A source=file row keeps the original soft delete
    (enabled=false), matching v07's never-hard-delete stance: the next sync_from_file()
    run re-enables it as long as it's still in proxies.txt, exactly like removing then
    re-adding the line, and hard-deleting it here would just lose that history for no
    reason (the file is still the real source of truth for that row)."""
    proxy = _get_proxy_or_404(db, proxy_id)
    if proxy.source == ProxySource.MANUAL:
        db.delete(proxy)
        db.commit()
        response.status_code = 204
        return None
    proxy.enabled = False
    db.commit()
    return _proxy_to_dict(proxy)
