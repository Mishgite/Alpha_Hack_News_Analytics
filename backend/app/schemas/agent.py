"""структурированные планы, проверки и результаты работы агента"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .insights import InsightResult


class DraftStatement(BaseModel):
    """принимает вывод и выбранные отрывки, дословные цитаты подставляет сервер"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=700)
    company_feature_refs: list[str] = Field(default_factory=list, max_length=6)
    condition: str | None = Field(default=None, max_length=300)
    evidence_ids: dict[str, Annotated[list[str], Field(min_length=1, max_length=3)]] = (
        Field(min_length=1, max_length=3)
    )


class CompanyStatement(DraftStatement):
    """связывает вывод о компании хотя бы с одним переданным признаком"""

    company_feature_refs: list[str] = Field(min_length=1, max_length=6)


class ConditionalStatement(DraftStatement):
    """требует условие, при котором возможен риск или возможность"""

    condition: str = Field(min_length=1, max_length=300)


class AnalysisDraft(BaseModel):
    """принимает только выводы модели, ID и метаданные источников добавляет сервер"""

    model_config = ConfigDict(extra="forbid")
    facts: list[DraftStatement] = Field(min_length=1, max_length=3)
    why_important: list[CompanyStatement] = Field(default_factory=list, max_length=2)
    risks: list[ConditionalStatement] = Field(default_factory=list, max_length=2)
    opportunities: list[ConditionalStatement] = Field(
        default_factory=list, max_length=2
    )
    recommendations: list[DraftStatement] = Field(default_factory=list, max_length=2)
    bank_position: DraftStatement | None = None
    limitations: list[str] = Field(default_factory=list, max_length=8)


class SearchPlan(BaseModel):
    """ограничивает число поисковых запросов и перечень используемых признаков"""

    model_config = ConfigDict(extra="forbid")
    queries: list[str] = Field(min_length=1, max_length=3)
    feature_keys: list[str] = Field(default_factory=list, max_length=12)


class Review(BaseModel):
    """фиксирует недостатки доказательств и запросы для одного повторного поиска"""

    model_config = ConfigDict(extra="forbid")
    supported: bool
    issues: list[str] = Field(default_factory=list, max_length=12)
    queries: list[str] = Field(default_factory=list, max_length=2)


class AnalysisOutput(BaseModel):
    """передаёт worker результат вместе с полнотой и журналом этапов"""

    result: InsightResult
    status: Literal["ready", "partial"]
    trace: list[dict]


class FollowupAnswer(BaseModel):
    """содержит ответ с проверяемыми цитатами и ограничениями"""

    model_config = ConfigDict(extra="forbid")
    statements: list[DraftStatement] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def require_answer(self):
        """разрешает честный ответ об отсутствии данных, но не полностью пустой результат"""
        if not self.statements and not any(item.strip() for item in self.limitations):
            raise ValueError("Answer requires statements or limitations")
        return self
