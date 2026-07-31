from fastapi import FastAPI

from app.routers import auth, health, jobs, stream

app = FastAPI(title="spotdl-web")

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(stream.router)
