import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProxySource(str, enum.Enum):
    FILE = "file"
    MANUAL = "manual"


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(nullable=True)
    source: Mapped[ProxySource] = mapped_column(
        Enum(ProxySource, name="proxy_source", values_callable=lambda cls: [e.value for e in cls]),
        nullable=False,
    )
