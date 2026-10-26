"""чтение сохранённых разборов, заданий и истории уточнений"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.schemas.api import AnalysisRequest, QuestionRequest
from app.schemas.database import (
    AnalysisData,
    ContextData,
    JobData,
    QuestionData,
    UserData,
)
from app.schemas.quality import UsefulnessRating
from app.services import InsightService
from app.services.questions import QuestionService
from app.services.ranking import RANKING_VERSION
from app.services.reports import ReportService
from app.services.runtime import RuntimeService

from .dependencies import get_current_user, get_insight_service

router = APIRouter(tags=["AI-разбор"])


def get_quality_service():
    from app.services.quality import QualityService

    return QualityService()


@router.get("/analyses/{analysis_id}/feedback")
def get_usefulness(
    analysis_id: UUID,
    user: UserData = Depends(get_current_user),
    service=Depends(get_quality_service),
):
    """возвращает личную оценку после проверки доступа к разбору"""
    return service.feedback(user.id, analysis_id)


@router.put("/analyses/{analysis_id}/feedback")
def set_usefulness(
    analysis_id: UUID,
    data: UsefulnessRating,
    user: UserData = Depends(get_current_user),
    service=Depends(get_quality_service),
):
    """сохраняет оценку разбора, не меняя интересы и рейтинг новостей"""
    return service.feedback(user.id, analysis_id, data.useful, write=True)


def get_runtime_service():
    """предоставляет состояние фонового обработчика"""
    return RuntimeService()


def get_report_service():
    """предоставляет сервис источников аналитики"""
    return ReportService()


def get_question_service():
    """предоставляет сервис уточняющих вопросов"""
    return QuestionService()


@router.post("/news/{news_id}/analysis", status_code=202, response_model=JobData)
def request_analysis(
    news_id: UUID,
    data: AnalysisRequest,
    user: UserData = Depends(get_current_user),
    service: InsightService = Depends(get_insight_service),
    runtime: RuntimeService = Depends(get_runtime_service),
):
    """возвращает прежнее задание, для нового запроса проверяет доступность worker"""
    existing = service.find_requested_job(
        user.id, news_id, idempotency_key=data.idempotency_key
    )
    if existing is not None:
        return existing
    state = runtime.get("worker")
    if (
        not state
        or (datetime.now(UTC) - state["updated_at"]).total_seconds() > 60
        or state["value"].get("status") != "running"
        or not state["value"].get("analysis_enabled")
    ):
        raise HTTPException(503, "Analysis worker unavailable")
    if not runtime.generation_available():
        raise HTTPException(503, "Analysis generation paused")
    return service.request_analysis(
        user.id, news_id, idempotency_key=data.idempotency_key
    )


@router.get("/analysis-jobs/{job_id}", response_model=JobData)
def get_job(
    job_id: UUID,
    user: UserData = Depends(get_current_user),
    service: InsightService = Depends(get_insight_service),
):
    """возвращает состояние существующего задания после проверки доступа"""
    return service.get_job(user.id, job_id)


@router.get("/analyses/{analysis_id}", response_model=AnalysisData)
def get_analysis(
    analysis_id: UUID,
    user: UserData = Depends(get_current_user),
    service: InsightService = Depends(get_insight_service),
):
    """возвращает сохранённый разбор выбранной компании с источниками"""
    return service.get_analysis(user.id, analysis_id)


@router.get(
    "/analyses/{analysis_id}/conversations/{conversation_id}",
    response_model=list[QuestionData],
)
def get_history(
    analysis_id: UUID,
    conversation_id: UUID,
    limit: int = Query(5, ge=1, le=50),
    user: UserData = Depends(get_current_user),
    service: InsightService = Depends(get_insight_service),
):
    """возвращает сохранённые сообщения из диалога текущего пользователя"""
    return service.get_history(user.id, analysis_id, conversation_id, limit=limit)


@router.post("/analyses/{analysis_id}/questions", response_model=QuestionData)
async def ask_question(
    analysis_id: UUID,
    data: QuestionRequest,
    user: UserData = Depends(get_current_user),
    service: QuestionService = Depends(get_question_service),
    runtime: RuntimeService = Depends(get_runtime_service),
):
    """возвращает и сохраняет проверенный ответ в контексте исходного разбора"""
    if not runtime.generation_available():
        raise HTTPException(503, "Analysis generation paused")
    return await service.ask(user.id, analysis_id, data.conversation_id, data.question)


@router.get("/analyses/{analysis_id}/trace")
def get_trace(
    analysis_id: UUID,
    user: UserData = Depends(get_current_user),
    service: InsightService = Depends(get_insight_service),
):
    """показывает выполненные шаги и ID источников после проверки доступа"""
    return service.get_analysis(user.id, analysis_id).trace


@router.get("/analyses/{analysis_id}/context", response_model=ContextData)
def get_analysis_context(
    analysis_id: UUID,
    user: UserData = Depends(get_current_user),
    service: InsightService = Depends(get_insight_service),
):
    """возвращает снимок признаков, на которые опирался сохранённый разбор"""
    return service.get_analysis_context(user.id, analysis_id)


@router.get("/report-chunks/{chunk_id}")
def get_report_chunk(
    chunk_id: UUID,
    user: UserData = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
):
    """возвращает цитируемый фрагмент, страницу и сведения о распознавании"""
    return service.get_chunk(chunk_id)


@router.get("/report-chunks/{chunk_id}/document")
def get_report_document(
    chunk_id: UUID,
    user: UserData = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
):
    """отдаёт исходный PDF только из локального каталога отчётов"""
    chunk = service.get_chunk(chunk_id)
    root = Path(__file__).resolve().parents[2] / "data/reports"
    target = (root / chunk.filename).resolve()
    if (
        target.parent != root.resolve()
        or target.suffix.lower() != ".pdf"
        or not target.is_file()
    ):
        raise HTTPException(404, "Source PDF is not available")
    expected_hash = (chunk.source_span_json or {}).get("original_sha256")
    if expected_hash:
        try:
            with target.open("rb") as source:
                actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
        except FileNotFoundError:
            raise HTTPException(404, "Source PDF is not available") from None
        except OSError:
            raise HTTPException(503, "Source PDF could not be read") from None
        if actual_hash != expected_hash:
            raise HTTPException(409, "Source PDF differs from the cited version")
    return FileResponse(target, media_type="application/pdf", filename=target.name)


@router.get("/status")
def get_processing_status(
    user: UserData = Depends(get_current_user),
    runtime: RuntimeService = Depends(get_runtime_service),
):
    """сообщает фронтенду доступность worker и последнее состояние биржевого источника"""
    state = runtime.get("worker")
    alive = bool(
        state
        and state["value"].get("status") == "running"
        and (datetime.now(UTC) - state["updated_at"]).total_seconds() <= 60
    )
    return {
        "database": "ready",
        "worker_alive": alive,
        "analysis_available": bool(
            alive
            and state["value"].get("analysis_enabled")
            and runtime.generation_available()
        ),
        "ranking": RANKING_VERSION,
        "market": runtime.get("market"),
        "llm_budget": runtime.get("llm_budget"),
        "monitoring": runtime.get("monitoring"),
    }
