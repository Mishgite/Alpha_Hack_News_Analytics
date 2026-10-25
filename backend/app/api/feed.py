"""лента, чтение новостей и обратная связь"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.schemas.api import (
    FeedRequest,
    ImpressionRequest,
    NewsOpenRequest,
    ReactionRequest,
    TagFeedbackRequest,
)
from app.schemas.database import InteractionData, ReactionCounts, SnapshotPage, UserData
from app.schemas.news import StoredNews
from app.services import FeedbackService, FeedService, NewsService

from .dependencies import (
    get_current_user,
    get_feed_service,
    get_feedback_service,
    get_news_service,
)

router = APIRouter(tags=["Лента"])


@router.post("/feed", response_model=SnapshotPage, status_code=201)
def create_feed(
    data: FeedRequest,
    user: UserData = Depends(get_current_user),
    service: FeedService = Depends(get_feed_service),
):
    """создаёт снимок ленты из размеченных новостей и возвращает первую страницу"""
    return service.create_feed(user.id, days=data.days, page_size=data.page_size)


@router.get("/feed/{snapshot_id}", response_model=SnapshotPage)
def get_feed_page(
    snapshot_id: UUID,
    position: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: UserData = Depends(get_current_user),
    service: FeedService = Depends(get_feed_service),
):
    """возвращает страницу существующего снимка без повторного ранжирования"""
    return service.get_page(user.id, snapshot_id, position=position, limit=limit)


@router.get("/news/{news_id}", response_model=StoredNews)
def get_news(
    news_id: UUID,
    user: UserData = Depends(get_current_user),
    service: NewsService = Depends(get_news_service),
):
    """возвращает текст и признаки новости из общего новостного корпуса"""
    return service.get_news(news_id)


@router.put("/news/{news_id}/reaction", response_model=ReactionCounts)
def set_reaction(
    news_id: UUID,
    data: ReactionRequest,
    user: UserData = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    """ставит или снимает реакцию на новость из доступного пользователю снимка"""
    return service.set_reaction(
        user.id, news_id, data.reaction, snapshot_id=data.snapshot_id
    )


@router.post("/impressions", response_model=InteractionData)
def record_impression(
    data: ImpressionRequest,
    user: UserData = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    """сохраняет показ новости, повторный event_id не создаёт второй показ"""
    return service.record_impression(user_id=user.id, **data.model_dump())


@router.post("/news/{news_id}/open", response_model=InteractionData)
def record_open(
    news_id: UUID,
    data: NewsOpenRequest,
    user: UserData = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    """сохраняет открытие новости из ленты, обычное чтение GET событие не создаёт"""
    return service.record_open(user_id=user.id, news_id=news_id, **data.model_dump())


@router.post("/news/{news_id}/tag-feedback", status_code=201)
def report_tags(
    news_id: UUID,
    data: TagFeedbackRequest,
    user: UserData = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    """сохраняет ошибку тегирования без изменения интересов пользователя"""
    return service.report_tags(user.id, news_id, **data.model_dump())
