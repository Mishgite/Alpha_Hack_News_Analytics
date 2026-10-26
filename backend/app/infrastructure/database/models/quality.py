"""личная оценка полезности разбора, отдельная от реакции на тему новости"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, timestamp


class AnalysisFeedback(Base):
    """хранит одну изменяемую оценку пользователя на сохранённый разбор"""

    __tablename__ = "analysis_feedback"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("ai_analyses.id", ondelete="CASCADE"), primary_key=True)
    useful: Mapped[bool]
    updated_at: Mapped[datetime] = timestamp(server_default=func.now(), onupdate=func.now())
