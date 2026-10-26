from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import (
    Base,
    CreatedAt,
    UUIDPrimaryKey,
    json_array,
    json_object,
    timestamp,
)


class NewsSource(Base):
    """настройки источника и позиция, с которой продолжать загрузку"""

    __tablename__ = "news_sources_registry"
    __table_args__ = (
        CheckConstraint("sync_interval_minutes > 0", name="positive_interval"),
    )
    code: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    enabled: Mapped[bool] = mapped_column(server_default="true")
    sync_interval_minutes: Mapped[int] = mapped_column(server_default="60")
    last_success_at: Mapped[datetime | None] = timestamp()
    source_cursor: Mapped[str | None]
    quota_state_json: Mapped[dict] = json_object()


class SourceRun(UUIDPrimaryKey, Base):
    """результат отдельной загрузки: сколько материалов получено и где возникли ошибки"""

    __tablename__ = "source_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','ready','partial','failed')", name="status"
        ),
        CheckConstraint(
            "fetched >= 0 AND created_news >= 0 AND duplicates >= 0", name="counts"
        ),
    )
    source_code: Mapped[str] = mapped_column(
        ForeignKey("news_sources_registry.code"), index=True
    )
    started_at: Mapped[datetime] = timestamp(server_default=func.now())
    finished_at: Mapped[datetime | None] = timestamp()
    status: Mapped[str] = mapped_column(server_default="running")
    fetched: Mapped[int] = mapped_column(server_default="0")
    created_news: Mapped[int] = mapped_column(server_default="0")
    duplicates: Mapped[int] = mapped_column(server_default="0")
    errors_json: Mapped[list] = json_array()


class NewsEvent(UUIDPrimaryKey, CreatedAt, Base):
    """объединяет публикации об одном событии; ручное разделение отключает автоматическую группировку"""

    __tablename__ = "news_events"
    matching_version: Mapped[str]
    automatic: Mapped[bool] = mapped_column(server_default="true")


class News(UUIDPrimaryKey, CreatedAt, Base):
    """текст материала и признаки его текущей версии; старые признаки сбрасываются при обновлении"""

    __tablename__ = "news"
    __table_args__ = (
        CheckConstraint(
            "tagging_status IN ('pending_tagging','ready','fallback','failed')",
            name="tag_status",
        ),
        CheckConstraint(
            "external_id IS NOT NULL OR canonical_url IS NOT NULL", name="source_key"
        ),
        CheckConstraint(
            "external_id IS NULL OR length(external_id) > 0", name="external_id"
        ),
        # проверяем уникальность только заполненных id: некоторые источники дают лишь ссылку
        Index(
            "uq_news_source_external",
            "canonical_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index(
            "uq_news_source_url_hash",
            "canonical_source",
            "url_hash",
            unique=True,
            postgresql_where=text("url_hash IS NOT NULL"),
        ),
        Index(
            "ix_news_ready_published",
            "published_at",
            postgresql_where=text("tagging_status = 'ready'"),
        ),
        Index("ix_news_event_window", "language", "published_at"),
    )
    canonical_source: Mapped[str] = mapped_column(
        ForeignKey("news_sources_registry.code")
    )
    external_id: Mapped[str | None]
    title: Mapped[str]
    text: Mapped[str]
    summary: Mapped[str | None]
    published_at: Mapped[datetime] = timestamp()
    fetched_at: Mapped[datetime] = timestamp(server_default=func.now())
    canonical_url: Mapped[str | None]
    url_hash: Mapped[str | None]
    content_hash: Mapped[str] = mapped_column(index=True)
    story_cluster_id: Mapped[UUID | None] = mapped_column(index=True)
    language: Mapped[str] = mapped_column(server_default="ru")
    tagging_status: Mapped[str] = mapped_column(server_default="pending_tagging")
    tagging_version: Mapped[str | None]
    extracted_features: Mapped[dict | None]


class NewsAttribution(UUIDPrimaryKey, Base):
    """ссылка на публикацию в источнике, связанная с сохранённой новостью"""

    __tablename__ = "news_attributions"
    __table_args__ = (
        UniqueConstraint("news_id", "url"),
        Index(
            "uq_attribution_source_external",
            "source_code",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"))
    source_code: Mapped[str] = mapped_column(ForeignKey("news_sources_registry.code"))
    url: Mapped[str]
    published_at: Mapped[datetime | None] = timestamp()
    external_id: Mapped[str | None]
    license_label: Mapped[str | None]


class NewsTag(CreatedAt, Base):
    """связь новости с темой; уверенность разметчика и вес качества хранятся отдельно"""

    __tablename__ = "news_tags"
    __table_args__ = (
        CheckConstraint("llm_confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("quality_weight BETWEEN 0 AND 2", name="weight_range"),
    )
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("tags.id"), primary_key=True, index=True
    )
    llm_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    quality_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), server_default="1")
    tagger_version: Mapped[str | None]


class UserReaction(Base):
    """текущий лайк или дизлайк пользователя на новость

    при снятии реакции строка удаляется
    """

    __tablename__ = "user_reactions"
    __table_args__ = (
        CheckConstraint("reaction IN ('like','dislike')", name="reaction"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    reaction: Mapped[str]
    updated_at: Mapped[datetime] = timestamp(
        server_default=func.now(), onupdate=func.now()
    )


class ReactionTotal(Base):
    """общие счётчики лайков и дизлайков, которые поддерживает триггер PostgreSQL"""

    __tablename__ = "reaction_totals"
    __table_args__ = (
        CheckConstraint(
            "likes_cnt >= 0 AND dislikes_cnt >= 0", name="nonnegative_counts"
        ),
    )
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"), primary_key=True)
    likes_cnt: Mapped[int] = mapped_column(server_default="0")
    dislikes_cnt: Mapped[int] = mapped_column(server_default="0")
    recalculated_at: Mapped[datetime] = timestamp(server_default=func.now())


class TagFeedback(UUIDPrimaryKey, CreatedAt, Base):
    """сообщение о неверной разметке; обычный дизлайк сюда не записывается"""

    __tablename__ = "tag_feedback"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"))
    wrong_tag_ids: Mapped[list] = json_array()
    suggested_tag_ids: Mapped[list] = json_array()
