raise RuntimeError("v21 rollback test: deliberate crash, reverted immediately after")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, health, jobs, proxies, settings, stream, tracks, worker

app = FastAPI(title="spotdl-web")

# v12: both production (nginx's /api/ proxy inside the `web` container) and local dev
# (Vite's dev-server /api proxy) are same-origin by default, so this middleware's allowlist
# normally never gets exercised by a real cross-origin browser request at all — it's a
# fallback for whoever bypasses the proxy (e.g. hitting this container's published port
# directly), not the real enforcement boundary. credentials=True still forbids a wildcard
# origin regardless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(proxies.router)
app.include_router(settings.router)
app.include_router(stream.router)
app.include_router(tracks.router)
app.include_router(worker.router)
