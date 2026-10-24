"""чтение сохранённых разборов, заданий и истории уточнений"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.database import AnalysisData, JobData, QuestionData, UserData
from app.services import InsightService

from .dependencies import get_current_user, get_insight_service

router = APIRouter(tags=["AI-разбор"])


@router.post("/news/{news_id}/analysis", status_code=501)
def request_analysis(news_id: UUID, user: UserData = Depends(get_current_user)):
    """сообщает, что обработчик AI ещё не подключён, не создаёт зависшее задание"""
    raise HTTPException(501, "AI analysis is not connected yet")


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
