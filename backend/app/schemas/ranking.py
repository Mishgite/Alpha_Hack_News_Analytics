from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .news import NewsFeatures

Weight = Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
JobRole = Literal["ceo", "cfo", "accountant", "treasury", "employee", "other"]
RankingMethod = Literal["weighted_formula_v1", "knn_cosine_v1"]


class RankingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    company_id: str
    job_role: JobRole
    # веса уже объединены из интересов компании, должности, настроек и реакций
    tag_weights: dict[str, Weight]
    company_tag_ids: list[str] = Field(default_factory=list)
    personal_tag_ids: list[str] = Field(default_factory=list)
    industry_code: str | None = None
    country_code: str | None = None
    registered_region_code: str | None = None
    # неизвестную географию работы не заменяем регионом регистрации компании
    operating_region_codes: list[str] | None = None
    known_factor_interests: list[str] = Field(default_factory=list)
    profile_version: str


class NewsCandidate(BaseModel):
    published_at: AwareDatetime
    features: NewsFeatures
    # отсутствие веса означает 1.0; эти веса относятся к качеству тегов, а не к вкусам пользователя
    tag_quality_weights: dict[str, Weight] = Field(default_factory=dict)


class RankingRequest(BaseModel):
    profile: RankingProfile
    candidates: list[NewsCandidate]
    now: AwareDatetime


class RankedNews(BaseModel):
    """раздельные баллы совпадения, свежести и итоговой сортировки одной новости"""

    news_id: UUID
    match_score: Score
    freshness_score: Score
    final_score: Score
    geography_score: Score | None = None
    geography_bonus: Score = 0
    geography_factor: Score = 1
    geography_reason: str | None = None
    ranking_version: str | None = None
    matched_signals: list[str] = Field(default_factory=list)
    reason: str


class RankingResult(BaseModel):
    """результат выбранного алгоритма; method и version сохраняются вместе с лентой"""

    method: RankingMethod
    version: str
    items: list[RankedNews]
