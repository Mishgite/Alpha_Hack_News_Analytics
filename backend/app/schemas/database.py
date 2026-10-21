"""данные для передачи из репозиториев: только значения, без ORM-объектов и сессий"""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
)

from .insights import InsightResult
from .ranking import JobRole, RankedNews, RankingMethod, Weight


class Record(BaseModel):
    """паттерн DTO: общий тип данных, которые репозитории возвращают вызывающему коду

    содержит значения полей, без ORM-сессии и ленивой загрузки
    """

    # model_validate читает поля ORM-записи, пока сессия открыта, и собирает отдельный DTO
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)


class CompanyData(Record):
    id: str
    profile_version: str
    okved_code: str | None = None
    okved_name: str | None = None
    industry: str | None = None
    city: str | None = None
    region: str | None = None
    revenue: Decimal | None = None
    group_id: str | None = None
    profile_json: dict[str, JsonValue] = Field(default_factory=dict)
    industry_code: str | None = None
    country_code: str | None = None
    registered_region_code: str | None = None
    operating_region_codes: list[str] | None = None
    known_factor_interests: list[str] = Field(default_factory=list)


class TagData(Record):
    id: str
    display_name: str


class UserData(Record):
    id: UUID
    company_id: str
    city: str
    job_role: JobRole
    access_role: str


class ContextData(Record):
    id: UUID
    company_id: str
    context_hash: str
    payload_json: dict[str, JsonValue]
    source_versions_json: dict[str, JsonValue]


class SessionData(Record):
    id: UUID
    user_id: UUID
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None


class TagReactionCounts(Record):
    likes: int = Field(ge=0)
    dislikes: int = Field(ge=0)


class CompanyTagInput(Record):
    """корпоративная тема, её происхождение и исходный вес для построения интересов"""

    tag_id: str
    origin: Literal["rule", "manual"]
    base_weight: Weight


class ProfileInputs(Record):
    """данные компании, настройки пользователя и реакции для расчёта весов тем"""

    user: UserData
    company: CompanyData
    company_tags: list[CompanyTagInput]
    personal_tag_ids: list[str]
    disabled_tag_ids: list[str]
    reaction_counts: dict[str, TagReactionCounts]


class SnapshotData(Record):
    id: UUID
    user_id: UUID
    company_id: str
    ranking_method: RankingMethod
    ranking_version: str
    expires_at: AwareDatetime


class FeedEntry(Record):
    position: int
    ranking: RankedNews
    title: str
    summary: str | None
    published_at: AwareDatetime
    source_url: str | None
    tags: list[str]


class SnapshotPage(Record):
    """новости из сохранённой ленты и позиция начала следующей страницы"""

    snapshot_id: UUID
    items: list[FeedEntry]
    next_position: int | None
    has_more: bool


class ReactionCounts(Record):
    news_id: UUID
    likes_cnt: int
    dislikes_cnt: int


class InteractionData(Record):
    event_id: UUID
    user_id: UUID
    news_id: UUID
    snapshot_id: UUID | None
    event_type: str
    occurred_at: AwareDatetime


class AnalysisData(Record):
    id: UUID
    company_id: str
    news_id: UUID
    # в таблице поле называется result_json, а вызывающий код получает разобранный InsightResult
    result: InsightResult = Field(
        validation_alias=AliasChoices("result", "result_json")
    )
    trace: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("trace", "agent_trace_json"),
    )
    cache_key: str
    status: str
    expires_at: AwareDatetime | None


class QuestionData(Record):
    id: UUID
    user_id: UUID
    analysis_id: UUID
    conversation_id: UUID
    question: str
    answer: str
    sources_json: list[JsonValue]
    created_at: AwareDatetime


class AnalysisWrite(Record):
    result: InsightResult
    company_context_id: UUID
    news_content_hash: str
    model_id: str
    prompt_version: str
    report_corpus_version: str
    agent_version: str
    retrieval_version: str
    context_hash: str
    cache_key: str
    agent_trace_json: list[dict[str, JsonValue]] = Field(default_factory=list)
    status: str = "ready"
    expires_at: AwareDatetime | None = None


class JobData(Record):
    id: UUID
    user_id: UUID
    company_id: str
    news_id: UUID
    analysis_id: UUID | None
    status: str
    worker_id: str | None
    attempts: int
    lease_until: AwareDatetime | None
    error_code: str | None


class ReportChunkData(Record):
    """текст фрагмента отчёта, номер страницы и данные документа для ссылки"""

    id: UUID
    report_id: UUID
    page_num: int
    chunk_no: int
    text: str
    source_span_json: dict[str, JsonValue] | None
    filename: str
    title: str
    report_date: date | None
    source_url: str | None
