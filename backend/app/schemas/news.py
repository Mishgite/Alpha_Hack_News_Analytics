from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class NewsForTagging(BaseModel):
    """очищенный текст для извлечения признаков; служебных полей БД здесь нет"""

    model_config = ConfigDict(extra="forbid")

    news_id: UUID
    title: str
    text: str
    published_at: AwareDatetime
    source_url: str | None = None


class NewsTag(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str
    # показывает уверенность разметчика в выбранном теге
    confidence: float = Field(ge=0, le=1)


class Geography(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    region_codes: list[str] = Field(default_factory=list)
    # значение None означает неизвестный масштаб, False указывает, что событие не общенациональное
    nationwide: bool | None = None


class NewsFeatures(BaseModel):
    """признаки одной версии новости; используются одинаково формулой и kNN"""

    model_config = ConfigDict(extra="forbid")

    news_id: UUID
    tags: list[NewsTag]
    event_type: str | None = None
    affected_factors: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    geography: Geography
    summary: str | None = None


class StoredNews(NewsForTagging):
    content_hash: str
    tagging_status: str
    tagging_version: str | None = None
    features: NewsFeatures | None = None
