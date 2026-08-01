from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, health, jobs, stream

app = FastAPI(title="spotdl-web")

# The SPA and API are served from different origins (different port locally, different
# subdomain once v12 wires the real tunnel) — cookie-authenticated fetch() calls need this,
# and credentials=True forbids a wildcard origin.
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
app.include_router(stream.router)
