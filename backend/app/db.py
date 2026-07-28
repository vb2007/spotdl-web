from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, create_engine
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        UUID: PgUUID(as_uuid=True),
    }


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
