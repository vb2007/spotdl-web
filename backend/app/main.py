from fastapi import FastAPI

from app.routers import auth, health

app = FastAPI(title="spotdl-web")

app.include_router(health.router)
app.include_router(auth.router)
