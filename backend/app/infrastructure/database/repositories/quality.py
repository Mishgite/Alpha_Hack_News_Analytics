"""читает показатели обработки и сохраняет оценки полезности без текстов пользователей"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.infrastructure.database.models import AIAnalysis, AnalysisJob, LLMUsage, News
from app.infrastructure.database.models.news import NewsSource
from app.infrastructure.database.models.quality import AnalysisFeedback
from app.infrastructure.database.models.runtime import ProcessingState


class QualityRepository:
    """паттерн Repository: собирает агрегаты, проверка доступа выполняется сервисом"""

    def __init__(self, session):
        self._session = session

    def feedback(self, user_id, analysis_id, useful=None, *, write=False):
        if write:
            statement = insert(AnalysisFeedback).values(
                user_id=user_id, analysis_id=analysis_id, useful=useful
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=["user_id", "analysis_id"],
                    set_={"useful": useful, "updated_at": func.now()},
                )
            )
        return self._session.scalar(
            select(AnalysisFeedback.useful).where(
                AnalysisFeedback.user_id == user_id,
                AnalysisFeedback.analysis_id == analysis_id,
            )
        )

    def snapshot(self):
        """читает счётчики за сутки и ограниченную историю операций, отсутствие оценок не заменяет нулём"""
        now = datetime.now(UTC)
        day = now - timedelta(days=1)
        jobs = dict(
            self._session.execute(
                select(AnalysisJob.status, func.count())
                .where(AnalysisJob.created_at >= day)
                .group_by(AnalysisJob.status)
            ).all()
        )
        calls = dict(
            self._session.execute(
                select(LLMUsage.status, func.count())
                .where(
                    LLMUsage.created_at
                    >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                )
                .group_by(LLMUsage.status)
            ).all()
        )
        votes, useful = self._session.execute(
            select(func.count(), func.count().filter(AnalysisFeedback.useful)).where(
                AnalysisFeedback.updated_at >= now - timedelta(days=30)
            )
        ).one()
        newest = self._session.scalar(
            select(func.max(News.published_at))
            .join(NewsSource, NewsSource.code == News.canonical_source)
            .where(
                News.tagging_status == "ready",
                News.published_at <= now,
                NewsSource.kind != "demo",
            )
        )
        pending = self._session.scalar(
            select(func.count())
            .select_from(News)
            .where(News.tagging_status == "pending_tagging")
        )
        operations = {
            row.key.removeprefix("operation:"): dict(row.value)
            for row in self._session.scalars(
                select(ProcessingState).where(ProcessingState.key.like("operation:%"))
            )
        }
        return {
            "captured_at": now.isoformat(),
            "jobs_24h": jobs,
            "llm_calls_today": calls,
            "pending_news": pending,
            "newest_ready_news": newest.isoformat() if newest else None,
            "usefulness_30d": {
                "votes": votes,
                "useful": useful,
                "rate": useful / votes if votes else None,
            },
            "operations": operations,
        }

    def recent_analyses(self, limit=100):
        """возвращает ограниченную выборку сохранённых результатов для локальной оценки"""
        rows = self._session.scalars(
            select(AIAnalysis)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id)
            .limit(limit)
        )
        return [
            {
                "id": str(row.id),
                "company_id": row.company_id,
                "news_id": str(row.news_id),
                "created_at": row.created_at.isoformat(),
                "model": row.model_id,
                "prompt": row.prompt_version,
                "corpus": row.report_corpus_version,
                "result": dict(row.result_json),
            }
            for row in rows
        ]
