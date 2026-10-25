from datetime import UTC, datetime
from uuid import UUID

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import InteractionData, ReactionCounts
from app.schemas.services import Reaction


class FeedbackService:
    """паттерн Service Layer: сохраняет реакции и показы новостей из ленты пользователя"""

    def __init__(self, *, uow_factory=UnitOfWork):
        """сохраняет фабрику транзакций для реакций и показов

        внедрение зависимостей (Dependency Injection): uow_factory задаёт способ создания UnitOfWork
        """
        self._uow = uow_factory

    def set_reaction(
        self, user_id: UUID, news_id: UUID, reaction: Reaction, *, snapshot_id: UUID
    ) -> ReactionCounts:
        """ставит like или dislike, снимает реакцию при none и возвращает счётчики новости

        проверяет доступ к ленте и наличие в ней новости
        повтор той же реакции не меняет счётчики
        """
        if snapshot_id is None:
            raise ValueError("snapshot_id is required")
        with self._uow() as db:
            result = db.feedback.set_reaction(
                user_id, news_id, reaction, snapshot_id=snapshot_id
            )
            db.commit()
            return result.model_copy(update={"my_reaction": reaction})

    def record_impression(
        self,
        *,
        event_id: UUID,
        user_id: UUID,
        snapshot_id: UUID,
        news_id: UUID,
        occurred_at: datetime,
    ) -> InteractionData:
        """записывает показ новости из доступной пользователю ленты

        принимает время с часовым поясом, не позднее текущего
        при повторном event_id возвращает уже записанный показ
        """
        if (
            snapshot_id is None
            or occurred_at.tzinfo is None
            or occurred_at > datetime.now(UTC)
        ):
            raise ValueError(
                "A snapshot and non-future timezone-aware time are required"
            )
        with self._uow() as db:
            result = db.feedback.record_impression(
                event_id=event_id,
                user_id=user_id,
                snapshot_id=snapshot_id,
                news_id=news_id,
                occurred_at=occurred_at,
            )
            db.commit()
            return result

    def report_tags(
        self, user_id, news_id, *, snapshot_id, wrong_tag_ids, suggested_tag_ids
    ):
        """сохраняет жалобу на разметку отдельно от персонального дизлайка"""
        with self._uow() as db:
            result = db.feedback.report_tags(
                user_id, news_id, snapshot_id, wrong_tag_ids, suggested_tag_ids
            )
            db.commit()
            return result

    def record_open(
        self,
        *,
        event_id: UUID,
        user_id: UUID,
        snapshot_id: UUID,
        news_id: UUID,
        occurred_at: datetime,
    ) -> InteractionData:
        """сохраняет открытие из доступной ленты без текста новости и данных браузера"""
        if (
            snapshot_id is None
            or occurred_at.tzinfo is None
            or occurred_at > datetime.now(UTC)
        ):
            raise ValueError(
                "A snapshot and non-future timezone-aware time are required"
            )
        with self._uow() as db:
            result = db.feedback.record_open(
                event_id=event_id,
                user_id=user_id,
                snapshot_id=snapshot_id,
                news_id=news_id,
                occurred_at=occurred_at,
            )
            db.commit()
            return result
