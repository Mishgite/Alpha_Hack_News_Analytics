from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import SnapshotPage
from app.schemas.ranking import RankingRequest, RankingResult
from app.schemas.services import ProfilePolicy

from ._common import company_context, digest, required
from .profiles import build_profile


class FeedService:
    """паттерн Service Layer: создаёт ленту через ранжировщик и возвращает страницы сохранённой ленты"""

    def __init__(
        self,
        *,
        ranker=None,
        ranking_config_version: str = "v1",
        feature_schema_version: str = "v1",
        policy: ProfilePolicy | None = None,
        uow_factory=UnitOfWork,
    ):
        """сохраняет ранжировщик, настройки весов и версии конфигурации

        без ranker доступны только сохранённые ленты

        внедрение зависимостей (Dependency Injection): uow_factory задаёт способ создания UnitOfWork
        паттерн Strategy: ranker задаёт алгоритм ранжирования, его можно заменить без изменения сервиса
        """
        self._uow = uow_factory
        self._ranker = ranker
        self._policy = (policy or ProfilePolicy()).model_copy(deep=True)
        self._feature_version = required(
            feature_schema_version, "feature_schema_version"
        )
        self._config_hash = digest(
            {
                "ranking": required(ranking_config_version, "ranking_config_version"),
                "features": self._feature_version,
                "policy": self._policy.model_dump(mode="json"),
            }
        )

    def get_page(
        self, user_id: UUID, snapshot_id: UUID, *, position: int = 0, limit: int = 20
    ) -> SnapshotPage:
        """возвращает страницу снимка после проверки владельца, выбранной компании и срока действия"""
        with self._uow() as db:
            return db.feeds.get_page(
                user_id, snapshot_id, position=position, limit=limit
            )

    def create_feed(
        self,
        user_id: UUID,
        *,
        days: int = 7,
        candidate_limit: int = 500,
        page_size: int = 20,
        ttl_minutes: int = 30,
    ) -> SnapshotPage:
        """ранжирует новости, сохраняет их порядок и возвращает первую страницу

        вызывает ranker после закрытия сессии БД
        перед сохранением проверяет, что профиль и новости не изменились
        отклоняет дубли и новости, которых не было среди кандидатов
        """
        if self._ranker is None:
            raise ValueError("A ranker must be configured to create a feed")
        if (
            not 1 <= days <= 365
            or not 1 <= page_size <= 100
            or not 1 <= ttl_minutes <= 1440
        ):
            raise ValueError("Invalid feed window, page size or TTL")
        now = datetime.now(UTC)
        with self._uow() as db:
            inputs = db.users.get_profile_inputs(user_id)
            profile = build_profile(inputs, self._policy)
            known_tags = {tag.id for tag in db.news.list_tags()}
            if set(profile.tag_weights) - known_tags:
                raise ValueError("Profile policy contains unknown or inactive tags")
            candidates = db.news.list_candidates(
                since=now - timedelta(days=days), as_of=now, limit=candidate_limit
            )

        request = RankingRequest(profile=profile, candidates=candidates, now=now)
        result = self._ranker(request.model_copy(deep=True))
        result = RankingResult.model_validate(result)
        ids = [item.news_id for item in result.items]
        if len(ids) != len(set(ids)) or set(ids) - {
            item.features.news_id for item in candidates
        }:
            raise ValueError("Ranker returned duplicate or unknown news")
        if not result.version.strip():
            raise ValueError("Ranker version is required")

        with self._uow() as db:
            current = build_profile(db.users.get_profile_inputs(user_id), self._policy)
            if current != profile:
                raise ValueError("Profile changed during ranking; rebuild the feed")
            db.news.check_candidates(candidates)
            context = company_context(db, inputs.company)
            snapshot = db.feeds.save(
                profile=profile,
                result=result,
                context_id=context.id,
                expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
                candidate_cutoff_at=now,
                feature_schema_version=self._feature_version,
                config_hash=self._config_hash,
            )
            page = db.feeds.get_page(user_id, snapshot.id, limit=page_size)
            db.commit()
            return page
