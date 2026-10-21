from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReferenceId = Annotated[str, Field(min_length=1)]


class InsightRequest(BaseModel):
    news_id: UUID
    company_id: str
    # автор запроса нужен для проверки доступа; общий разбор кешируется для компании и новости
    requested_by_user_id: UUID


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: ReferenceId
    title: str = Field(min_length=1)
    url: str | None = None
    page: int | None = Field(default=None, ge=1)
    excerpt: str | None = None


class EvidenceStatement(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1)
    # ссылки указывают на id из общего списка источников конкретного разбора
    source_refs: list[ReferenceId] = Field(min_length=1)
    company_feature_refs: list[ReferenceId] = Field(default_factory=list)
    condition: str | None = None


class InsightResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_id: UUID
    company_id: str
    facts: list[EvidenceStatement]
    why_important: list[EvidenceStatement]
    risks: list[EvidenceStatement]
    opportunities: list[EvidenceStatement]
    recommendations: list[EvidenceStatement]
    bank_position: EvidenceStatement | None
    source_refs: list[SourceReference]
    limitations: list[str]

    @model_validator(mode="after")
    def check_references(self):
        # проверяем связь утверждений с источниками; достоверность самого текста проверяет AI-модуль
        ids = {source.id for source in self.source_refs}
        if len(ids) != len(self.source_refs):
            raise ValueError("Duplicate source reference")
        statements = (
            self.facts
            + self.why_important
            + self.risks
            + self.opportunities
            + self.recommendations
        )
        if self.bank_position:
            statements.append(self.bank_position)
        if any(set(statement.source_refs) - ids for statement in statements):
            raise ValueError("Statement refers to an unknown source")
        return self
