"""состояние фоновой обработки между перезапусками приложения"""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, json_object, timestamp


class ProcessingState(Base):
    """хранит версию обработанного профиля, задержку повтора и heartbeat воркера"""

    __tablename__ = "processing_states"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict] = json_object()
    updated_at: Mapped[datetime] = timestamp(
        server_default=func.now(), onupdate=func.now()
    )
