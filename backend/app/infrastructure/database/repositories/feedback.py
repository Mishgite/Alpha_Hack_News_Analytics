from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    FeedSnapshotItem,
    InteractionEvent,
    News,
    ReactionTotal,
    UserReaction,
)
from app.infrastructure.database.repositories.feed import FeedRepository
from app.infrastructure.database.repositories.profiles import _require_user
from app.schemas.database import InteractionData, ReactionCounts


class FeedbackRepository:
    """паттерн Repository: записывает реакции и показы, возвращает счётчики новостей

    счётчики обновляет триггер PostgreSQL
    """

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def _validate_snapshot(
        self, user_id: UUID, snapshot_id: UUID | None, news_id: UUID
    ):
        """при переданном snapshot_id проверяет доступ к ленте и наличие в ней новости"""
        if snapshot_id is not None:
            FeedRepository(self._session).get_for_user(user_id, snapshot_id)
            exists = self._session.scalar(
                select(FeedSnapshotItem.position).where(
                    FeedSnapshotItem.snapshot_id == snapshot_id,
                    FeedSnapshotItem.news_id == news_id,
                )
            )
            if exists is None:
                raise PermissionError("News was not part of this feed")

    def set_reaction(
        self,
        user_id: UUID,
        news_id: UUID,
        reaction: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> ReactionCounts:
        """ставит, меняет или удаляет реакцию пользователя и возвращает общие счётчики новости

        повтор той же реакции не создаёт событие; snapshot_id включает проверку принадлежности ленте
        """
        if reaction not in {"like", "dislike", "none"}:
            raise ValueError("Unknown reaction")
        user = _require_user(self._session, user_id, lock=True)
        self._validate_snapshot(user_id, snapshot_id, news_id)
        # сначала блокируем пользователя, затем новость: параллельные реакции обновляются по очереди
        news = self._session.scalar(
            select(News).where(News.id == news_id).with_for_update()
        )
        if news is None:
            raise LookupError("News not found")
        current = self._session.get(UserReaction, (user_id, news_id))
        previous = current.reaction if current else "none"
        # повтор того же запроса не меняет реакцию и не добавляет событие в историю
        if previous != reaction:
            if reaction == "none":
                self._session.delete(current)
            elif current is None:
                self._session.add(
                    UserReaction(
                        user_id=user_id,
                        news_id=news_id,
                        company_id=user.company_id,
                        reaction=reaction,
                    )
                )
            else:
                current.reaction, current.company_id = reaction, user.company_id
            self._session.add(
                InteractionEvent(
                    event_id=uuid4(),
                    user_id=user_id,
                    company_id=user.company_id,
                    snapshot_id=snapshot_id,
                    news_id=news_id,
                    event_type="reaction_clear"
                    if reaction == "none"
                    else "reaction_set",
                    payload_json={"previous": previous, "reaction": reaction},
                    occurred_at=datetime.now(UTC),
                )
            )
            self._session.flush()
        # счётчики меняет триггер БД, в том числе при удалении пользователя вместе с реакциями
        self._session.execute(
            insert(ReactionTotal)
            .values(news_id=news_id, likes_cnt=0, dislikes_cnt=0)
            .on_conflict_do_nothing(index_elements=["news_id"])
        )
        return ReactionCounts.model_validate(
            self._session.get(ReactionTotal, news_id, populate_existing=True)
        )

    def record_impression(
        self,
        *,
        event_id: UUID,
        user_id: UUID,
        snapshot_id: UUID,
        news_id: UUID,
        occurred_at: datetime,
    ) -> InteractionData:
        """записывает показ из доступной ленты или возвращает прежнее событие по event_id

        повторный ID для другого пользователя, снимка или новости вызывает ValueError
        """
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include timezone")
        user = _require_user(self._session, user_id, lock=True)
        self._validate_snapshot(user_id, snapshot_id, news_id)
        self._session.execute(
            insert(InteractionEvent)
            .values(
                event_id=event_id,
                user_id=user_id,
                company_id=user.company_id,
                snapshot_id=snapshot_id,
                news_id=news_id,
                event_type="impression",
                payload_json={},
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        event = self._session.get(InteractionEvent, event_id)
        # повторный event_id допустим только для того же показа, иначе это конфликт запросов
        if (event.user_id, event.snapshot_id, event.news_id, event.event_type) != (
            user_id,
            snapshot_id,
            news_id,
            "impression",
        ):
            raise ValueError("event_id already used for a different interaction")
        return InteractionData.model_validate(event)
