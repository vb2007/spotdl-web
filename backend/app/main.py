from fastapi import FastAPI

from app.routers import health

app = FastAPI(title="spotdl-web")

app.include_router(health.router)
