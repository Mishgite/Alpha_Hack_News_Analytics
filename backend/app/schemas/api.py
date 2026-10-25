"""тела запросов и ответы, которые отличаются от моделей сервисов"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from .database import UserData
from .services import Reaction, ServiceInput


class SessionResponse(BaseModel):
    """возвращает токен при создании сессии, не скрывая его при сериализации в JSON"""

    user: UserData
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_at: AwareDatetime


class CompanySelection(ServiceInput):
    """содержит компанию, на которую переключается пользователь"""

    company_id: str = Field(min_length=1, max_length=200)


class FeedRequest(ServiceInput):
    """ограничивает период новостей и размер первой страницы ленты"""

    days: int = Field(default=7, ge=1, le=365)
    page_size: int = Field(default=20, ge=1, le=100)


class ReactionRequest(ServiceInput):
    """связывает реакцию с лентой, в которой пользователь увидел новость"""

    snapshot_id: UUID
    reaction: Reaction


class NewsOpenRequest(ServiceInput):
    """связывает открытие с новостью из снимка ленты"""

    event_id: UUID
    snapshot_id: UUID
    occurred_at: AwareDatetime


class ImpressionRequest(ServiceInput):
    """передаёт показ новости с уникальным ID для защиты от повторной записи"""

    event_id: UUID
    snapshot_id: UUID
    news_id: UUID
    occurred_at: AwareDatetime


class TagFeedbackRequest(ServiceInput):
    """связывает жалобу на темы с просмотренным снимком ленты"""

    snapshot_id: UUID
    wrong_tag_ids: list[str] = Field(default_factory=list, max_length=50)
    suggested_tag_ids: list[str] = Field(default_factory=list, max_length=50)


class AnalysisRequest(ServiceInput):
    """один ключ соответствует одной пользовательской попытке запуска разбора"""

    idempotency_key: str = Field(min_length=1, max_length=200)


class QuestionRequest(ServiceInput):
    """передаёт вопрос в конкретный диалог по разбору"""

    conversation_id: UUID
    question: str = Field(min_length=1, max_length=1000)
