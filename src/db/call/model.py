from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, utcnow

if TYPE_CHECKING:
    from src.db.evaluation.model import CallEvaluation
    from src.db.manager.model import Manager


class CallStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    IGNORED = "IGNORED"


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_file_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus), default=CallStatus.PENDING, nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    manager: Mapped["Manager"] = relationship("Manager", back_populates="calls")
    evaluation: Mapped["CallEvaluation | None"] = relationship(
        "CallEvaluation",
        back_populates="call",
        uselist=False,
        cascade="all, delete-orphan",
    )
