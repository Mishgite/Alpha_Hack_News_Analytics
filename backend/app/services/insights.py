from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import JsonValue

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import (
    AnalysisData,
    AnalysisWrite,
    JobData,
    QuestionData,
    ReportChunkData,
)
from app.schemas.insights import InsightResult, SourceReference
from app.schemas.services import AnalysisVersions, AnalysisWork

from ._common import company_context, digest, required


def _require_lease(job: JobData, worker_id: str, attempt: int) -> None:
    """проверяет worker, номер попытки и срок, до которого можно завершить задание"""
    if (
        job.status != "running"
        or job.worker_id != worker_id
        or job.attempts != attempt
        or job.lease_until is None
        or job.lease_until <= datetime.now(UTC)
    ):
        raise ValueError("Worker lease is missing, expired or superseded")


def _cache_key(work: AnalysisWork) -> str:
    """вычисляет ключ по полной версии новости, контексту компании и версиям AI-компонентов"""
    return digest(
        {
            "company": work.job.company_id,
            "news": work.news.model_dump(mode="json"),
            "context": work.context.context_hash,
            "versions": work.versions.model_dump(mode="json"),
        }
    )


class InsightService:
    """паттерн Service Layer: готовит задания для AI, сохраняет разборы и ответы на вопросы по ним"""

    def __init__(self, *, uow_factory=UnitOfWork):
        """сохраняет фабрику транзакций для заданий, разборов и истории

        внедрение зависимостей (Dependency Injection): uow_factory задаёт способ создания UnitOfWork
        """
        self._uow = uow_factory

    def request_analysis(
        self, user_id: UUID, news_id: UUID, *, idempotency_key: str
    ) -> JobData:
        """создаёт задание на разбор новости для выбранной компании

        при повторном idempotency_key возвращает прежнее задание пользователя
        """
        with self._uow() as db:
            db.news.get(news_id)
            job = db.analyses.create_job(
                user_id,
                news_id,
                idempotency_key=required(idempotency_key, "idempotency_key"),
            )
            db.commit()
            return job

    def get_job(self, user_id: UUID, job_id: UUID) -> JobData:
        """возвращает состояние задания после проверки владельца и выбранной компании"""
        with self._uow() as db:
            return db.analyses.get_job_for_user(user_id, job_id)

    def get_analysis(self, user_id: UUID, analysis_id: UUID) -> AnalysisData:
        """возвращает сохранённый разбор в выбранной компании, включая результаты с истёкшим кешем"""
        with self._uow() as db:
            return db.analyses.get_for_user(user_id, analysis_id)

    def claim_job(
        self, worker_id: str, *, lease_seconds: int = 120, max_attempts: int = 3
    ) -> JobData | None:
        """выдаёт worker задание, номер попытки и срок обработки

        задания без оставшихся попыток помечает failed
        если доступных заданий нет, возвращает None
        """
        with self._uow() as db:
            job = db.analyses.claim_job(
                required(worker_id, "worker_id"),
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )
            db.commit()
            return job

    def prepare_job(
        self, job_id: UUID, worker_id: str, attempt: int, *, versions: AnalysisVersions
    ) -> AnalysisWork:
        """собирает данные для AI в AnalysisWork и закрывает сессию БД

        проверяет, что задание принадлежит worker и компания пользователя не изменилась
        """
        with self._uow() as db:
            job = db.analyses.get_job(job_id)
            _require_lease(job, worker_id, attempt)
            profile = db.users.get_profile_inputs(job.user_id)
            if profile.company.id != job.company_id:
                raise PermissionError("Selected company changed after analysis request")
            work = AnalysisWork(
                job=job,
                news=db.news.get(job.news_id),
                context=company_context(db, profile.company),
                versions=versions,
                cache_key="",
            )
            work.cache_key = _cache_key(work)
            db.commit()
            return work

    def get_cached_result(self, work: AnalysisWork) -> AnalysisData | None:
        """возвращает готовый разбор из кеша или None

        проверяет попытку обработки, контекст компании и версию новости
        """
        with self._uow() as db:
            job = db.analyses.get_job(work.job.id)
            _require_lease(job, work.job.worker_id, work.job.attempts)
            self._check_work(db, work, job)
            result = db.analyses.get_cached_result(job.user_id, _cache_key(work))
            return result if result is not None and result.status == "ready" else None

    def _check_work(self, db: UnitOfWork, work: AnalysisWork, job: JobData) -> None:
        """проверяет задание, компанию и новость из AnalysisWork перед сохранением результата

        удерживает блокировки компании и новости до конца транзакции
        """
        if (job.user_id, job.news_id, job.company_id) != (
            work.job.user_id,
            work.news.news_id,
            work.context.company_id,
        ):
            raise ValueError("Work does not match the stored job")
        profile = db.users.get_profile_inputs(job.user_id)
        if profile.company.id != job.company_id:
            raise PermissionError("Selected company changed during analysis")
        context = company_context(db, profile.company)
        if (
            context.id != work.context.id
            or context.context_hash != work.context.context_hash
        ):
            raise ValueError("Company context changed during analysis")
        current_news = db.news.get(job.news_id, lock=True)
        if current_news != work.news:
            raise ValueError("News changed during analysis; prepare a new work package")

    def complete_job(
        self,
        work: AnalysisWork,
        result: InsightResult,
        *,
        status: Literal["ready", "partial"] = "ready",
        ttl_hours: int = 24,
        trace: list[dict[str, JsonValue]] | None = None,
    ) -> AnalysisData:
        """сохраняет разбор и завершает задание в одной транзакции

        проверяет попытку, компанию, контекст и версию новости
        при ошибке отменяет запись результата
        status указывает полноту разбора, ttl_hours задаёт срок кеша
        trace содержит шаги, которые выполнил агент
        """
        if status not in {"ready", "partial"} or not 1 <= ttl_hours <= 720:
            raise ValueError("Invalid analysis status or TTL")
        if (result.news_id, result.company_id) != (
            work.news.news_id,
            work.context.company_id,
        ):
            raise ValueError("AI result belongs to another article or company")
        with self._uow() as db:
            job = db.analyses.get_job(work.job.id)
            _require_lease(job, work.job.worker_id, work.job.attempts)
            self._check_work(db, work, job)
            data = AnalysisWrite(
                result=result,
                company_context_id=work.context.id,
                news_content_hash=work.news.content_hash,
                context_hash=work.context.context_hash,
                cache_key=_cache_key(work),
                agent_trace_json=trace or [],
                **work.versions.model_dump(),
                status=status,
                expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
            )
            analysis = db.analyses.save(job.user_id, data)
            db.analyses.finish_job(
                job.id, work.job.worker_id, work.job.attempts, analysis_id=analysis.id
            )
            db.commit()
            return analysis

    def fail_job(
        self, job_id: UUID, worker_id: str, attempt: int, *, error_code: str
    ) -> JobData:
        """записывает код ошибки и переводит задание в failed

        проверяет, что попытка ещё принадлежит worker и её срок не истёк
        новую попытку автоматически не создаёт
        """
        with self._uow() as db:
            job = db.analyses.finish_job(
                job_id,
                worker_id,
                attempt,
                error_code=required(error_code, "error_code"),
            )
            db.commit()
            return job

    def search_reports(self, query: str, *, limit: int = 5) -> list[ReportChunkData]:
        """возвращает фрагменты готовых отчётов по русскому полнотекстовому поиску для RAG"""
        with self._uow() as db:
            return db.reports.search(query, limit=limit)

    def get_history(
        self, user_id: UUID, analysis_id: UUID, conversation_id: UUID, *, limit: int = 5
    ) -> list[QuestionData]:
        """возвращает последние сообщения пользователя в указанном диалоге от старых к новым"""
        with self._uow() as db:
            return db.analyses.get_history(
                user_id, analysis_id, conversation_id, limit=limit
            )

    def save_answer(
        self,
        user_id: UUID,
        analysis_id: UUID,
        conversation_id: UUID,
        *,
        question: str,
        answer: str,
        sources: list[SourceReference],
    ) -> QuestionData:
        """сохраняет вопрос, готовый ответ и ссылки на источники

        вопрос должен быть не длиннее 1000 символов, ответ и источники обязательны
        проверяет, что ID источников не повторяются
        """
        question, answer = required(question, "question"), required(answer, "answer")
        if len(question) > 1000:
            raise ValueError("Question exceeds 1000 characters")
        if not sources or len({source.id for source in sources}) != len(sources):
            raise ValueError("Answer requires sources with unique ids")
        with self._uow() as db:
            result = db.analyses.add_question(
                user_id,
                analysis_id,
                conversation_id,
                question,
                answer,
                [source.model_dump(mode="json") for source in sources],
            )
            db.commit()
            return result
