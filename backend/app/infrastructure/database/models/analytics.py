from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import (
    Base,
    CreatedAt,
    UUIDPrimaryKey,
    json_array,
    json_object,
    timestamp,
)


class AlfaReport(UUIDPrimaryKey, Base):
    """исходный аналитический документ и состояние его загрузки в поиск"""

    __tablename__ = "alfa_reports"
    __table_args__ = (
        CheckConstraint("status IN ('pending','ready','failed')", name="status"),
    )
    filename: Mapped[str]
    title: Mapped[str]
    report_date: Mapped[date | None]
    source_url: Mapped[str | None]
    file_hash: Mapped[str] = mapped_column(unique=True)
    ingested_at: Mapped[datetime] = timestamp(server_default=func.now())
    status: Mapped[str] = mapped_column(server_default="pending")


class AlfaReportChunk(UUIDPrimaryKey, Base):
    """фрагмент отчёта со страницей, чтобы найденный текст можно было связать с источником"""

    __tablename__ = "alfa_report_chunks"
    __table_args__ = (
        UniqueConstraint("report_id", "page_num", "chunk_no"),
        CheckConstraint("page_num >= 1 AND chunk_no >= 0", name="page_chunk"),
        Index("ix_alfa_report_chunks_fts", "terms_tsvector", postgresql_using="gin"),
    )
    report_id: Mapped[UUID] = mapped_column(ForeignKey("alfa_reports.id"))
    page_num: Mapped[int]
    chunk_no: Mapped[int]
    text: Mapped[str]
    # поисковое представление текста вычисляет PostgreSQL; вручную заполнять его не нужно
    terms_tsvector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian'::regconfig, text)", persisted=True)
    )
    source_span_json: Mapped[dict | None]


class AIAnalysis(UUIDPrimaryKey, CreatedAt, Base):
    """сохранённый разбор новости для компании с версиями данных, использованных при подготовке"""

    __tablename__ = "ai_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_context_id", "company_id"],
            ["company_context_snapshots.id", "company_context_snapshots.company_id"],
        ),
        UniqueConstraint(
            "id", "company_id", "news_id", name="uq_analysis_id_company_news"
        ),
        CheckConstraint("status IN ('ready','partial')", name="status"),
        Index(
            "ix_ai_analyses_company_news_created", "company_id", "news_id", "created_at"
        ),
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    company_context_id: Mapped[UUID]
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"))
    news_content_hash: Mapped[str]
    result_json: Mapped[dict] = json_object()
    sources_json: Mapped[list] = json_array()
    agent_trace_json: Mapped[list] = json_array()
    model_id: Mapped[str]
    prompt_version: Mapped[str]
    report_corpus_version: Mapped[str]
    agent_version: Mapped[str]
    retrieval_version: Mapped[str]
    context_hash: Mapped[str]
    cache_key: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default="ready")
    expires_at: Mapped[datetime | None] = timestamp()


class AnalysisJob(UUIDPrimaryKey, CreatedAt, Base):
    """состояние фонового задания, число попыток и срок, на который его забрал worker"""

    __tablename__ = "analysis_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id", "company_id", "news_id"],
            ["ai_analyses.id", "ai_analyses.company_id", "ai_analyses.news_id"],
        ),
        CheckConstraint(
            "status IN ('queued','running','ready','failed')", name="status"
        ),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index(
            "uq_analysis_jobs_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_analysis_jobs_user_status", "user_id", "status"),
        Index("ix_analysis_jobs_company_news", "company_id", "news_id"),
        Index("ix_analysis_jobs_queue", "status", "next_attempt_at", "created_at"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    news_id: Mapped[UUID] = mapped_column(ForeignKey("news.id"))
    analysis_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default="queued")
    started_at: Mapped[datetime | None] = timestamp()
    finished_at: Mapped[datetime | None] = timestamp()
    error_code: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(server_default="0")
    idempotency_key: Mapped[str | None]
    lease_until: Mapped[datetime | None] = timestamp()
    worker_id: Mapped[str | None]
    next_attempt_at: Mapped[datetime] = timestamp(server_default=func.now())


class AnalysisQuestion(UUIDPrimaryKey, CreatedAt, Base):
    """вопрос пользователя и ответ по разбору, доступные только этому пользователю"""

    __tablename__ = "analysis_questions"
    __table_args__ = (
        Index(
            "ix_questions_conversation",
            "analysis_id",
            "user_id",
            "conversation_id",
            "created_at",
        ),
    )
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("ai_analyses.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[UUID]
    question: Mapped[str]
    answer: Mapped[str]
    sources_json: Mapped[list] = json_array()


class LLMUsage(UUIDPrimaryKey, CreatedAt, Base):
    """запись вызова модели с количеством токенов и стоимостью"""

    __tablename__ = "llm_usage"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('tagger','analyst','verifier','followup')", name="task_type"
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND estimated_cost_rub >= 0",
            name="nonnegative_usage",
        ),
    )
    task_type: Mapped[str]
    model_id: Mapped[str]
    news_id: Mapped[UUID | None] = mapped_column(ForeignKey("news.id"))
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="SET NULL")
    )
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    estimated_cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    status: Mapped[str]
