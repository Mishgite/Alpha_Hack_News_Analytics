from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    AIAnalysis,
    AlfaReport,
    AlfaReportChunk,
    AnalysisJob,
    AnalysisQuestion,
    CompanyContextSnapshot,
    News,
)
from app.infrastructure.database.repositories.profiles import (
    _require_company_access,
    _require_user,
)
from app.schemas.database import (
    AnalysisData,
    AnalysisWrite,
    ContextData,
    JobData,
    QuestionData,
    ReportChunkData,
)


class AnalysisRepository:
    """паттерн Repository: читает и записывает AI-разборы, задания и вопросы в общей сессии"""

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def get_job(self, job_id: UUID) -> JobData:
        """возвращает задание для worker, для неизвестного ID вызывает LookupError

        права пользователя здесь не проверяет
        """
        row = self._session.get(AnalysisJob, job_id, populate_existing=True)
        if row is None:
            raise LookupError("Analysis job not found")
        return JobData.model_validate(row)

    def get_job_for_user(self, user_id: UUID, job_id: UUID) -> JobData:
        """возвращает задание после проверки его владельца и выбранной компании"""
        job = self.get_job(job_id)
        if job.user_id != user_id:
            raise PermissionError("Job belongs to another user")
        _require_company_access(self._session, user_id, job.company_id)
        return job

    def get_for_user(self, user_id: UUID, analysis_id: UUID) -> AnalysisData:
        """возвращает разбор выбранной компании; срок кеша и актуальность текста здесь не проверяются"""
        analysis = self._session.get(AIAnalysis, analysis_id)
        if analysis is None:
            raise LookupError("Analysis not found")
        _require_company_access(self._session, user_id, analysis.company_id)
        return AnalysisData.model_validate(analysis)

    def get_cached_result(self, user_id: UUID, cache_key: str) -> AnalysisData | None:
        # ключ с версиями контекста передаёт сервис; здесь проверяем компанию, срок и текущий текст новости
        """ищет разбор по ключу, компании, сроку кеша и хэшу новости

        возвращает DTO или None, статус разбора проверяет вызывающий сервис
        """
        user = _require_user(self._session, user_id, lock=True)
        row = self._session.scalar(
            select(AIAnalysis)
            .join(News, News.id == AIAnalysis.news_id)
            .where(
                AIAnalysis.company_id == user.company_id,
                AIAnalysis.cache_key == cache_key,
                AIAnalysis.news_content_hash == News.content_hash,
                or_(
                    AIAnalysis.expires_at.is_(None), AIAnalysis.expires_at > func.now()
                ),
            )
        )
        return AnalysisData.model_validate(row) if row else None

    def get_context_for_user(self, user_id: UUID, analysis_id: UUID) -> ContextData:
        """возвращает сохранённый контекст разбора после проверки доступа к компании"""
        self.get_for_user(user_id, analysis_id)
        analysis = self._session.get(AIAnalysis, analysis_id)
        context = self._session.get(CompanyContextSnapshot, analysis.company_context_id)
        if context is None:
            raise LookupError("Analysis context not found")
        return ContextData.model_validate(context)

    def save(self, user_id: UUID, data: AnalysisWrite) -> AnalysisData:
        """сохраняет разбор для указанной компании, контекста и версии новости

        возвращает готовый действующий кеш, если ключ и данные совпали
        иначе создаёт новый разбор, сохраняя старый по прежнему ID вместе с вопросами
        для того же ключа с другими входными данными вызывает ValueError
        """
        _require_company_access(self._session, user_id, data.result.company_id)
        context = self._session.get(CompanyContextSnapshot, data.company_context_id)
        if context is None or context.company_id != data.result.company_id:
            raise PermissionError("Context belongs to another company")
        news = self._session.scalar(
            select(News)
            .where(
                News.id == data.result.news_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if news is None or news.content_hash != data.news_content_hash:
            raise ValueError("Article changed while analysis was being prepared")
        if context.context_hash != data.context_hash:
            raise ValueError("Context hash does not match stored context")
        # блокировка новости заставляет параллельные записи её разборов ждать друг друга
        # возвращаем действующий кеш, старый разбор сохраняем по прежнему ID
        existing = self._session.scalar(
            select(AIAnalysis).where(AIAnalysis.cache_key == data.cache_key)
        )
        if existing is not None:
            identity = (
                existing.company_id,
                existing.news_id,
                existing.company_context_id,
                existing.news_content_hash,
                existing.model_id,
                existing.prompt_version,
                existing.report_corpus_version,
                existing.agent_version,
                existing.retrieval_version,
            )
            expected = (
                data.result.company_id,
                data.result.news_id,
                data.company_context_id,
                data.news_content_hash,
                data.model_id,
                data.prompt_version,
                data.report_corpus_version,
                data.agent_version,
                data.retrieval_version,
            )
            if identity != expected:
                raise ValueError("Cache key reused for another analysis context")
            if existing.status in {"ready", "partial"} and (
                existing.expires_at is None or existing.expires_at > datetime.now(UTC)
            ):
                return AnalysisData.model_validate(existing)
            existing.cache_key = f"archived:{existing.id}"
            self._session.flush()
        values = data.model_dump(exclude={"result"})
        row = AIAnalysis(
            **values,
            company_id=data.result.company_id,
            news_id=data.result.news_id,
            result_json=data.result.model_dump(mode="json"),
            sources_json=[
                source.model_dump(mode="json") for source in data.result.source_refs
            ],
        )
        self._session.add(row)
        self._session.flush()
        return AnalysisData.model_validate(row)

    def add_question(
        self,
        user_id: UUID,
        analysis_id: UUID,
        conversation_id: UUID,
        question: str,
        answer: str,
        sources: list,
    ) -> QuestionData:
        """проверяет доступ к разбору и сохраняет вопрос, готовый ответ и источники в личном диалоге"""
        self.get_for_user(user_id, analysis_id)
        record = AnalysisQuestion(
            user_id=user_id,
            analysis_id=analysis_id,
            conversation_id=conversation_id,
            question=question,
            answer=answer,
            sources_json=sources,
        )
        self._session.add(record)
        self._session.flush()
        return QuestionData.model_validate(record)

    def get_history(
        self, user_id: UUID, analysis_id: UUID, conversation_id: UUID, *, limit: int = 5
    ) -> list[QuestionData]:
        """возвращает последние сообщения указанного пользователя и диалога в хронологическом порядке"""
        self.get_for_user(user_id, analysis_id)
        if not 1 <= limit <= 100:
            raise ValueError("Invalid history limit")
        rows = list(
            self._session.scalars(
                select(AnalysisQuestion)
                .where(
                    AnalysisQuestion.user_id == user_id,
                    AnalysisQuestion.analysis_id == analysis_id,
                    AnalysisQuestion.conversation_id == conversation_id,
                )
                .order_by(
                    AnalysisQuestion.created_at.desc(), AnalysisQuestion.id.desc()
                )
                .limit(limit)
            )
        )
        # запрос выбрал последние сообщения, а в ответе они идут от старого к новому
        return [QuestionData.model_validate(row) for row in rows[::-1]]

    def create_job(
        self, user_id: UUID, news_id: UUID, *, idempotency_key: str
    ) -> JobData:
        """создаёт задание для выбранной компании либо возвращает прежнее по ключу пользователя

        использование прежнего ключа для другой компании или новости вызывает ValueError
        """
        if not idempotency_key.strip():
            raise ValueError("Non-empty idempotency key required")
        user = _require_user(self._session, user_id, lock=True)
        existing = self._session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.user_id == user_id,
                AnalysisJob.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            pending = self._session.scalar(
                select(func.count())
                .select_from(AnalysisJob)
                .where(
                    AnalysisJob.user_id == user_id,
                    AnalysisJob.status.in_(["queued", "running"]),
                )
            )
            if pending >= 3:
                raise ValueError("At most three analysis jobs may be pending")
        self._session.execute(
            insert(AnalysisJob)
            .values(
                user_id=user_id,
                company_id=user.company_id,
                news_id=news_id,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "idempotency_key"],
                index_where=AnalysisJob.idempotency_key.is_not(None),
            )
        )
        job = self._session.scalars(
            select(AnalysisJob).where(
                AnalysisJob.user_id == user_id,
                AnalysisJob.idempotency_key == idempotency_key,
            )
        ).one()
        # один ключ можно повторять для прежнего запроса, но нельзя привязать к другой новости
        if job.company_id != user.company_id or job.news_id != news_id:
            raise ValueError("Idempotency key reused with another company or article")
        return JobData.model_validate(job) if job is not None else None

    def claim_job(
        self, worker_id: str, *, lease_seconds: int = 120, max_attempts: int = 3
    ) -> JobData | None:
        """выдаёт задание worker, пропуская строки, заблокированные другими обработчиками

        увеличивает номер попытки и задаёт срок обработки
        задания без оставшихся попыток помечает failed
        """
        if not worker_id or lease_seconds < 1 or max_attempts < 1:
            raise ValueError("Invalid lease settings")
        now = datetime.now(UTC)
        exhausted = list(
            self._session.scalars(
                select(AnalysisJob.id)
                .where(
                    AnalysisJob.attempts >= max_attempts,
                    or_(
                        AnalysisJob.status == "queued",
                        (AnalysisJob.status == "running")
                        & (AnalysisJob.lease_until <= now),
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        )
        if exhausted:
            self._session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id.in_(exhausted))
                .values(
                    status="failed",
                    error_code="attempts_exhausted",
                    finished_at=now,
                    lease_until=None,
                )
            )
        job = self._session.scalar(
            select(AnalysisJob)
            .where(
                AnalysisJob.attempts < max_attempts,
                or_(
                    (AnalysisJob.status == "queued")
                    & (AnalysisJob.next_attempt_at <= now),
                    (AnalysisJob.status == "running")
                    & (AnalysisJob.lease_until <= now),
                ),
            )
            .order_by(AnalysisJob.created_at, AnalysisJob.id)
            # другой worker уже мог забрать строку; пропускаем её без ожидания
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
            .limit(1)
        )
        if job:
            job.status, job.worker_id = "running", worker_id
            job.started_at, job.lease_until = (
                now,
                now + timedelta(seconds=lease_seconds),
            )
            job.attempts += 1
            self._session.flush()
        return JobData.model_validate(job) if job is not None else None

    def finish_job(
        self,
        job_id: UUID,
        worker_id: str,
        attempt: int,
        *,
        analysis_id: UUID | None = None,
        error_code: str | None = None,
    ) -> JobData:
        """завершает попытку, записывая ID разбора или код ошибки

        проверяет worker, номер попытки и срок обработки
        """
        job = self._session.scalar(
            select(AnalysisJob)
            .where(AnalysisJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = datetime.now(UTC)
        # запоздалый worker не может завершить задание, которое уже выдали заново
        if (
            job is None
            or job.status != "running"
            or job.worker_id != worker_id
            or job.attempts != attempt
            or job.lease_until is None
            or job.lease_until <= now
        ):
            raise ValueError("Worker lease is missing, expired or superseded")
        if (analysis_id is None) == (error_code is None):
            raise ValueError("Provide either analysis_id or error_code")
        if error_code is not None:
            error_code = error_code.strip()
            if not error_code:
                raise ValueError("error_code must be non-empty")
        job.analysis_id, job.error_code = analysis_id, error_code
        job.status = "failed" if error_code else "ready"
        job.finished_at, job.lease_until = now, None
        self._session.flush()
        return JobData.model_validate(job) if job is not None else None


class ReportRepository:
    """паттерн Repository: ищет текст в загруженных аналитических отчётах"""

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def search(self, query: str, *, limit: int = 5) -> list[ReportChunkData]:
        """ищет фрагменты готовых отчётов с учётом русских словоформ

        возвращает текст, страницу и данные документа для ссылки
        запрос должен быть непустым, limit от 1 до 50
        """
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError("Query must be non-empty; limit must be in [1, 50]")
        # ищем в готовых фрагментах отчётов с учётом русских словоформ
        tsquery = func.websearch_to_tsquery("russian", query)
        rows = list(
            self._session.execute(
                select(AlfaReportChunk, AlfaReport)
                .join(AlfaReport, AlfaReport.id == AlfaReportChunk.report_id)
                .where(
                    AlfaReportChunk.terms_tsvector.op("@@")(tsquery),
                    AlfaReport.status == "ready",
                )
                .order_by(
                    func.ts_rank_cd(AlfaReportChunk.terms_tsvector, tsquery).desc(),
                    AlfaReportChunk.id,
                )
                .limit(limit)
            )
        )

        return [
            ReportChunkData(
                id=chunk.id,
                report_id=report.id,
                page_num=chunk.page_num,
                chunk_no=chunk.chunk_no,
                text=chunk.text,
                source_span_json=chunk.source_span_json,
                filename=report.filename,
                title=report.title,
                report_date=report.report_date,
                source_url=report.source_url,
            )
            for chunk, report in rows
        ]

    def save(self, report):
        """сохраняет неизменяемую версию отчёта и фрагменты в одной транзакции"""
        values = report.model_dump(exclude={"parts"})
        statement = (
            insert(AlfaReport)
            .values(**values, status="ready")
            .on_conflict_do_nothing(index_elements=[AlfaReport.file_hash])
            .returning(AlfaReport.id)
        )
        report_id = self._session.scalar(statement)
        if report_id is None:
            return self._session.scalar(
                select(AlfaReport.id).where(AlfaReport.file_hash == report.file_hash)
            )
        self._session.add_all(
            [
                AlfaReportChunk(report_id=report_id, **part.model_dump())
                for part in report.parts
            ]
        )
        self._session.flush()
        return report_id

    def versions(self):
        """возвращает хэши готовых версий в стабильном порядке"""
        return list(
            self._session.scalars(
                select(AlfaReport.file_hash)
                .where(AlfaReport.status == "ready")
                .order_by(AlfaReport.file_hash)
            )
        )

    def get_chunk(self, chunk_id):
        """находит фрагмент вместе с документом, неизвестный ID вызывает LookupError"""
        row = self._session.execute(
            select(AlfaReportChunk, AlfaReport)
            .join(AlfaReport)
            .where(AlfaReportChunk.id == chunk_id, AlfaReport.status == "ready")
        ).first()
        if row is None:
            raise LookupError("Report fragment not found")
        chunk, report = row
        return ReportChunkData(
            id=chunk.id,
            report_id=report.id,
            page_num=chunk.page_num,
            chunk_no=chunk.chunk_no,
            text=chunk.text,
            source_span_json=chunk.source_span_json,
            filename=report.filename,
            title=report.title,
            report_date=report.report_date,
            source_url=report.source_url,
        )
