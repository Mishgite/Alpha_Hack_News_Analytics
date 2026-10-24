"""создание сервисов и проверка сессии перед выполнением HTTP-запроса"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas.database import UserData
from app.services import (
    FeedbackService,
    FeedService,
    InsightService,
    NewsService,
    ProfileService,
)
from app.services.ranking_stub import rank_news

bearer = HTTPBearer(auto_error=False)


def get_profile_service() -> ProfileService:
    """внедрение зависимостей: предоставляет сервис профилей обработчику запроса"""
    return ProfileService()


def get_news_service() -> NewsService:
    """предоставляет сервис чтения новостей и справочника тем"""
    return NewsService()


def get_feed_service() -> FeedService:
    """подключает временный ранжировщик к существующему сервису ленты"""
    return FeedService(
        ranker=rank_news,
        ranking_config_version="stub-v1",
        feature_schema_version="news-features-v2",
    )


def get_feedback_service() -> FeedbackService:
    """предоставляет сервис реакций и показов"""
    return FeedbackService()


def get_insight_service() -> InsightService:
    """предоставляет сервис чтения сохранённых AI-разборов"""
    return InsightService()


def get_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """извлекает Bearer-токен из заголовка, при его отсутствии возвращает 401"""
    if credentials is None:
        raise HTTPException(
            401, "Session token required", headers={"WWW-Authenticate": "Bearer"}
        )
    return credentials.credentials


def get_current_user(
    token: str = Depends(get_token),
    service: ProfileService = Depends(get_profile_service),
) -> UserData:
    """проверяет срок и отзыв сессии, возвращает пользователя из БД"""
    try:
        return service.authenticate(token)
    except PermissionError:
        raise HTTPException(
            401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"}
        ) from None
