import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    team_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    monitor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="http")
    check_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    monitor_region: Mapped[str] = mapped_column(String(30), nullable=False, default="auto")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Custom headers & body (for authenticated API monitoring)
    custom_headers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    custom_body: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    expected_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Keyword monitoring
    keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keyword_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "contains" or "not_contains"

    # Maintenance window
    maintenance_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maintenance_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maintenance_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maintenance_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
