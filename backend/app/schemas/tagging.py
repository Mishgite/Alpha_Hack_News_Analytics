"""данные для разметки профилей и отчёт о пакетной обработке новостей"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .news import Geography, NewsTag


class ProfileForTagging(BaseModel):
    """передаёт разметчику известное местоположение и описание деятельности"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    city: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=30000)


class ProfileTags(BaseModel):
    """возвращает предложенные темы отдельно от географии, не изменяет настройки пользователя"""

    model_config = ConfigDict(extra="forbid")
    tags: list[NewsTag] = Field(max_length=50)
    geography: Geography


class NewsTaggingOutput(BaseModel):
    """проверяет ответ модели без идентификатора новости, который задаёт приложение"""

    model_config = ConfigDict(extra="forbid")
    tags: list[NewsTag] = Field(max_length=50)
    geography: Geography
    event_type: str | None = None
    affected_factors: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    summary: str | None = None


class ProcessingError(BaseModel):
    """указывает элемент с ошибкой, не раскрывая текст новости или ответ провайдера"""

    position: int | None = None
    news_id: UUID | None = None
    code: str


class ProcessingResult(BaseModel):
    """возвращает ID успешно обработанных новостей и ошибки отдельных элементов"""

    news_ids: list[UUID] = Field(default_factory=list)
    errors: list[ProcessingError] = Field(default_factory=list)
