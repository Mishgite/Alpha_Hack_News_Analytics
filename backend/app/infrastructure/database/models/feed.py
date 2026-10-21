from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import (
    Base,
    CreatedAt,
    UUIDPrimaryKey,
    json_object,
    timestamp,
)


class FeedSnapshot(UUIDPrimaryKey, CreatedAt, Base):
    """параметры конкретной выдачи: чей профиль использован, какой метод и до какого срока она доступна"""

    __tablename__ = "feed_snapshots"
    __table_args__ = (
        # составная ссылка не даст привязать к выдаче контекст другой компании
        ForeignKeyConstraint(
            ["company_context_id", "company_id"],
            ["company_context_snapshots.id", "company_context_snapshots.company_id"],
        ),
        CheckConstraint("expires_at > created_at", name="expiry"),
        CheckConstraint(
            "ranking_method IN ('weighted_formula_v1','knn_cosine_v1')",
            name="ranking_method",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    company_context_id: Mapped[UUID]
    ranking_version: Mapped[str]
    ranking_method: Mapped[str]
    model_version: Mapped[str | None]
    feature_schema_version: Mapped[str]
    config_hash: Mapped[str]
    preference_context_json: Mapped[dict] = json_object()
    candidate_cutoff_at: Mapped[datetime] = timestamp()
    expires_at: Mapped[datetime] = timestamp(index=True)


class FeedSnapshotItem(Base):
    """место новости в выдаче, её баллы и копия отображаемых полей на момент сохранения"""

    __tablename__ = "feed_snapshot_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "news_id"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint(
            "match_score BETWEEN 0 AND 1 AND freshness_score BETWEEN 0 AND 1 AND final_score BETWEEN 0 AND 1",
            name="score_range",
        ),
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("feed_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"))
    final_score: Mapped[float] = mapped_column(Float(53))
    match_score: Mapped[float]
    freshness_score: Mapped[float]
    ranking_details: Mapped[dict] = json_object()
    features_json: Mapped[dict] = json_object()


class InteractionEvent(Base):
    """история показов и действий; отличается от текущего состояния реакции пользователя"""

    __tablename__ = "interaction_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('impression','open','reaction_set','reaction_clear',"
            "'tag_error','analysis_feedback')",
            name="event_type",
        ),
    )
    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("feed_snapshots.id", ondelete="SET NULL")
    )
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"))
    event_type: Mapped[str]
    payload_json: Mapped[dict] = json_object()
    occurred_at: Mapped[datetime] = timestamp()
    received_at: Mapped[datetime] = timestamp(server_default=func.now(), index=True)
