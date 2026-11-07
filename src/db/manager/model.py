from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, utcnow

if TYPE_CHECKING:
    from src.db.call.model import Call


class Manager(Base):
    """Модель менеджера, чиї дзвінки оцінюються."""

    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    drive_folder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    calls: Mapped[list["Call"]] = relationship(
        "Call", back_populates="manager", cascade="all, delete-orphan"
    )

