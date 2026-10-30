"""A job's export (v64): every present file as one streamed zip, and an extended M3U.

Same owner-scoped gate as every other direct-id job endpoint (`_get_job_or_404`): a
non-owner's 404 is indistinguishable from a nonexistent job, and an admin may export any
job. Cookie session only (`require_session`), so an API key never reaches it. The
membership rule and the archive itself live in app/services/export.py.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.routers.auth import require_session
from app.routers.jobs import _get_job_or_404
from app.routers.tracks import _content_disposition
from app.services import app_settings, export, rollup

router = APIRouter(prefix="/api/jobs", tags=["export"])


def _plan(db: Session, job_id: uuid.UUID, user: User, *, limited: bool) -> export.ExportPlan:
    """The job's export plan. `limited` applies the zip's limits; the playlist has none
    (a few bytes per track, and over the zip's limit it's what the UI points to instead)."""
    job, _owner_email, _owner_username = _get_job_or_404(db, job_id, user)
    rows = export.load_rows(db, job.id)
    title = rollup.job_title(db, job)
    max_files, max_bytes = app_settings.export_limits(db)
    # Ends the transaction before the filesystem checks and before anything streams: the
    # response below may run for hours, and a connection idle in transaction all that time is
    # v31's leak. A commit hands the connection back to the pool; everything after this is
    # plain data, so nothing reads the session again (an attribute read would begin a new
    # transaction).
    db.commit()
    plan = export.plan_from_rows(rows, title)
    if limited and (len(plan.files) > max_files or plan.total_bytes > max_bytes):
        raise ApiError(
            413,
            "export_too_large",
            "This export is over the size limit",
            {
                "files": len(plan.files),
                "bytes": plan.total_bytes,
                "max_files": max_files,
                "max_bytes": max_bytes,
            },
            headers=_count_headers(plan),
        )
    return plan


def _count_headers(plan: export.ExportPlan) -> dict[str, str]:
    """How many of the job's tracks have a file on disk, out of how many: the open job's
    strip reads them from its HEAD (one request per opening, never per row), so its count is
    the zip's own, not the database's."""
    return {"X-Export-Files": str(len(plan.files)), "X-Export-Tracks": str(plan.total_tracks)}


async def _stream(archive):
    """The archive's chunks, read in the threadpool (file reads block). Closed explicitly
    when the client goes away: Starlette leaves an abandoned sync iterator to the garbage
    collector, which kept the file being read open (and its buffers alive) after every
    aborted download."""
    chunks = export.iter_chunks(archive)
    try:
        async for chunk in iterate_in_threadpool(chunks):
            yield chunk
    finally:
        # A cancelled read isn't abandoned mid-call (anyio waits for the thread), so the
        # generator isn't executing here and close() runs its cleanup at once.
        chunks.close()


# HEAD too, the v35 (e) probe: the frontend checks first, so a 404 or 413 shows inline
# instead of navigating to a JSON error page. It runs the same plan (the same limits, the
# same Content-Length) without reading a file.
@router.api_route("/{job_id}/export.zip", methods=["GET", "HEAD"])
def export_zip(
    job_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> Response:
    plan = _plan(db, job_id, user, limited=True)
    archive = export.build_zip(plan)
    headers = {
        "Content-Length": str(len(archive)),
        "Content-Disposition": _content_disposition(plan.archive_name),
        "Cache-Control": "no-store",
        # nginx's /api/ location already has proxy_buffering off; this says so per response.
        "X-Accel-Buffering": "no",
        **_count_headers(plan),
    }
    if request.method == "HEAD":
        return Response(status_code=200, media_type="application/zip", headers=headers)
    return StreamingResponse(_stream(archive), media_type="application/zip", headers=headers)


# HEAD too, for the same probe as the zip's.
@router.api_route("/{job_id}/playlist.m3u8", methods=["GET", "HEAD"])
def export_playlist(
    job_id: uuid.UUID,
    request: Request,
    paths: Literal["library"] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> Response:
    """The same tracks the zip holds, relative to it. `?paths=library` lists each file at
    its absolute path on disk instead (for a media server pointed at the library). That
    reveals the filesystem layout, so it's the admin's alone: anyone else gets
    `require_admin_hidden`'s answer, an unknown route's 404 (CLAUDE.md, v56)."""
    if paths == "library" and not user.is_admin:
        # Deliberately no `code`, as in require_admin_hidden.
        raise HTTPException(status_code=404, detail="Not Found")
    plan = _plan(db, job_id, user, limited=False)
    body = export.m3u_text(plan, absolute=paths == "library").encode("utf-8")
    headers = {
        "Content-Disposition": _content_disposition(plan.playlist_name),
        "Cache-Control": "no-store",
    }
    if request.method == "HEAD":
        headers["Content-Length"] = str(len(body))
        return Response(status_code=200, media_type="audio/x-mpegurl; charset=utf-8", headers=headers)
    return Response(content=body, media_type="audio/x-mpegurl; charset=utf-8", headers=headers)
