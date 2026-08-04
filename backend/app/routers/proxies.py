import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Proxy, ProxySource, UserSession
from app.routers.auth import require_session
from app.services.proxies import redact

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
    _: UserSession = Depends(require_session),
) -> list[dict]:
    proxies = db.query(Proxy).order_by(Proxy.source, Proxy.url).all()
    return [_proxy_to_dict(proxy) for proxy in proxies]


@router.post("", status_code=201)
def create_proxy(
    payload: CreateProxyRequest,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    """Adds a source=manual proxy -- pick_proxy() draws from it exactly like a
    source=file row (see v07). Deliberately doesn't hard-validate the URL format:
    spotdl's own accepted-proxy regex could change independently of this code, and a
    malformed entry is caught (and cooled down) the same way any real download failure
    is, the first time it's actually tried -- matching sync_from_file's stance."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

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
    _: UserSession = Depends(require_session),
) -> dict:
    proxy = _get_proxy_or_404(db, proxy_id)
    proxy.enabled = payload.enabled
    db.commit()
    return _proxy_to_dict(proxy)


@router.delete("/{proxy_id}")
def delete_proxy(
    proxy_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    """Soft delete (enabled=false) -- matches v07's never-hard-delete stance, which
    exists to preserve health history for a later re-add. For a source=file row, this is
    only a pause: the next sync_from_file() run re-enables it as long as it's still in
    proxies.txt, exactly like removing then re-adding the line."""
    proxy = _get_proxy_or_404(db, proxy_id)
    proxy.enabled = False
    db.commit()
    return _proxy_to_dict(proxy)
