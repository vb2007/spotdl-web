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


def begin_snapshot(db: Session) -> None:
    """Ends `db`'s current transaction and starts a REPEATABLE READ one, so every statement
    after this sees one consistent snapshot. Postgres' default READ COMMITTED gives each
    *statement* its own snapshot instead: a listing built from several statements (a count,
    per-status counts, the page) can then disagree with itself when a row commits between
    them -- v34.2 measured "9 items of 8" on 8 of 411 listings while jobs were being
    submitted. Postgres only; SQLite (the test suite) has no such level and is a single
    writer anyway."""
    db.commit()
    if db.get_bind().dialect.name == "postgresql":
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
