from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    CompanyContextSnapshot,
    FeedSnapshot,
    FeedSnapshotItem,
    News,
    NewsSource,
    NewsTag,
)
from app.infrastructure.database.repositories.profiles import (
    _require_company_access,
    _require_user,
)
from app.schemas.database import FeedEntry, SnapshotData, SnapshotPage
from app.schemas.ranking import RankedNews, RankingProfile, RankingResult


class FeedRepository:
    """паттерн Repository: сохраняет порядок новостей и возвращает страницы ленты с проверкой доступа"""

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def save(
        self,
        *,
        profile: RankingProfile,
        result: RankingResult,
        context_id: UUID,
        expires_at: datetime,
        candidate_cutoff_at: datetime,
        feature_schema_version: str,
        config_hash: str,
    ) -> SnapshotData:
        """сохраняет порядок, оценки и отображаемые поля новостей в новом снимке

        проверяет профиль пользователя, контекст компании, сроки и отсутствие повторяющихся новостей
        """
        user = _require_user(self._session, profile.user_id, lock=True)
        # пока считалась лента, пользователь мог изменить компанию или должность
        if user.company_id != profile.company_id or user.job_role != profile.job_role:
            raise ValueError("Profile changed; rebuild the ranking request")
        context = self._session.get(CompanyContextSnapshot, context_id)
        if context is None or context.company_id != user.company_id:
            raise PermissionError("Context does not match selected company")
        now = datetime.now(UTC)
        if (
            expires_at.tzinfo is None
            or expires_at <= now
            or candidate_cutoff_at.tzinfo is None
        ):
            raise ValueError("Invalid snapshot timestamps")
        ids = [item.news_id for item in result.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate news in feed")
        news = {
            row.id: row
            for row in self._session.scalars(select(News).where(News.id.in_(ids)))
        }
        if set(news) != set(ids):
            raise LookupError("News not found")
        qualities = {
            (row.news_id, row.tag_id): float(row.quality_weight)
            for row in self._session.scalars(
                select(NewsTag).where(NewsTag.news_id.in_(ids))
            )
        }
        source_kinds = dict(
            self._session.execute(
                select(NewsSource.code, NewsSource.kind).where(
                    NewsSource.code.in_({row.canonical_source for row in news.values()})
                )
            ).all()
        )
        snapshot = FeedSnapshot(
            user_id=user.id,
            company_id=user.company_id,
            company_context_id=context_id,
            ranking_method=result.method,
            ranking_version=result.version,
            feature_schema_version=feature_schema_version,
            config_hash=config_hash,
            preference_context_json=profile.model_dump(mode="json"),
            candidate_cutoff_at=candidate_cutoff_at,
            created_at=now,
            expires_at=expires_at,
        )
        self._session.add(snapshot)
        self._session.flush()
        # порядок уже рассчитан вызывающим сервисом; страницы читают его по сохранённой позиции
        for position, item in enumerate(result.items):
            article = news[item.news_id]
            features = article.extracted_features or {}
            self._session.add(
                FeedSnapshotItem(
                    snapshot_id=snapshot.id,
                    position=position,
                    news_id=item.news_id,
                    match_score=item.match_score,
                    freshness_score=item.freshness_score,
                    final_score=item.final_score,
                    ranking_details={
                        "reason": item.reason,
                        "matched_signals": item.matched_signals,
                        "ranking_version": result.version,
                        "geography_score": item.geography_score,
                        "geography_bonus": item.geography_bonus,
                        "geography_factor": item.geography_factor,
                        "geography_reason": item.geography_reason,
                        # признаки фиксируются до реакции, чтобы обучение не читало будущие изменения
                        "training_features": {
                            "schema_version": 3,
                            "business_scope": features.get("business_scope", "unknown"),
                            "business_relevance": features.get(
                                "business_relevance", 0.5
                            ),
                            "geography": features.get("geography", {}),
                            "content_hash": article.content_hash,
                            "tagging_version": article.tagging_version,
                            "synthetic": bool(
                                context.payload_json.get("profile_json", {}).get(
                                    "synthetic"
                                )
                            )
                            or source_kinds.get(article.canonical_source) == "demo",
                            "tags": [
                                {
                                    "id": tag["id"],
                                    "confidence": tag["confidence"],
                                    "quality_weight": qualities.get(
                                        (article.id, tag["id"]), 1.0
                                    ),
                                }
                                for tag in features.get("tags", [])
                            ],
                        },
                    },
                    # копируем отображаемые поля, чтобы правки новости не меняли уже выданную ленту
                    features_json={
                        "title": article.title,
                        "summary": article.summary,
                        "published_at": article.published_at.isoformat(),
                        "source_url": article.canonical_url,
                        "tags": [tag["id"] for tag in features.get("tags", [])],
                    },
                )
            )
        self._session.flush()
        return SnapshotData.model_validate(snapshot)

    def get_for_user(self, user_id: UUID, snapshot_id: UUID) -> SnapshotData:
        """возвращает снимок после проверки владельца, выбранной компании и срока действия"""
        row = self._session.get(FeedSnapshot, snapshot_id)
        if row is None:
            raise LookupError("Feed snapshot not found")
        if row.user_id != user_id:
            raise PermissionError("Feed belongs to another user")
        _require_company_access(self._session, user_id, row.company_id)
        if row.expires_at <= datetime.now(UTC):
            raise ValueError("Snapshot expired; refresh the feed")
        return SnapshotData.model_validate(row)

    def get_page(
        self, user_id: UUID, snapshot_id: UUID, *, position: int = 0, limit: int = 20
    ) -> SnapshotPage:
        """возвращает страницу доступного снимка с позиции position, признаком has_more и next_position"""
        if position < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid pagination")
        self.get_for_user(user_id, snapshot_id)
        # лишняя строка нужна только для has_more; в ответ войдёт не больше limit элементов
        rows = list(
            self._session.scalars(
                select(FeedSnapshotItem)
                .where(
                    FeedSnapshotItem.snapshot_id == snapshot_id,
                    FeedSnapshotItem.position >= position,
                )
                .order_by(FeedSnapshotItem.position)
                .limit(limit + 1)
            )
        )
        from app.infrastructure.database.models.news import UserReaction

        reactions = dict(
            self._session.execute(
                select(UserReaction.news_id, UserReaction.reaction).where(
                    UserReaction.user_id == user_id,
                    UserReaction.news_id.in_([r.news_id for r in rows]),
                )
            ).all()
        )
        snapshot = self._session.get(FeedSnapshot, snapshot_id)
        entries = [
            FeedEntry(
                position=row.position,
                my_reaction=reactions.get(row.news_id, "none"),
                ranking=RankedNews(
                    news_id=row.news_id,
                    match_score=row.match_score,
                    freshness_score=row.freshness_score,
                    final_score=row.final_score,
                    **row.ranking_details,
                ),
                **row.features_json,
            )
            for row in rows[:limit]
        ]
        return SnapshotPage(
            snapshot_id=snapshot_id,
            generated_at=snapshot.created_at,
            expires_at=snapshot.expires_at,
            items=entries,
            has_more=len(rows) > limit,
            next_position=rows[limit].position if len(rows) > limit else None,
        )
