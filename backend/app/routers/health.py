import logging
import time

from fastapi import APIRouter, Response
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import engine
from app.services.alerts import RedisOutageLog

logger = logging.getLogger(__name__)
router = APIRouter()
# v59 (O5): Docker probes this every ~30s; an outage logs one traceback, not one per probe.
_redis_outage = RedisOutageLog(
    logger, prefix="Health check", first="Redis unreachable", level=logging.ERROR
)


@router.get("/api/health")
def health(response: Response) -> dict:
    settings = get_settings()
    failing: list[str] = []

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check: Postgres unreachable")
        failing.append("postgres")

    try:
        # v12: this endpoint is now also polled every ~30s by Docker's own `api`
        # healthcheck (docker-compose.yml) — closing the client (a fresh connection pool
        # + socket per call, previously never released) matters at that cadence in a way
        # it didn't when only occasional manual/curl checks hit it.
        with Redis.from_url(settings.redis_url, socket_connect_timeout=2) as redis_client:
            redis_client.ping()
    except RedisError:
        _redis_outage.failed(time.time())
        failing.append("redis")
    else:
        _redis_outage.reached(time.time())

    if failing:
        response.status_code = 503
        return {"status": "error", "failing": failing}

    return {"status": "ok"}
