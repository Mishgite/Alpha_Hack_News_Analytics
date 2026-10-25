"""данные для вызова сервисов и результаты их работы"""

from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .database import ContextData, JobData, UserData
from .news import StoredNews
from .ranking import JobRole, Weight


class ServiceInput(BaseModel):
    """запрещает лишние поля и убирает пробелы по краям входных строк"""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    @field_validator("*")
    @classmethod
    def reject_null_characters(cls, value):
        """отклоняет нулевой символ, который PostgreSQL не принимает в текстовых полях"""
        items = value if isinstance(value, list) else [value]
        if any(isinstance(item, str) and "\x00" in item for item in items):
            raise ValueError("Text must not contain null characters")
        return value


class Registration(ServiceInput):
    """данные деморегистрации: существующая компания, город и должность пользователя"""

    company_id: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=200)
    job_role: JobRole = "other"


class UserSettings(ServiceInput):
    """город и должность, которые пользователь может изменить"""

    city: str = Field(min_length=1, max_length=200)
    job_role: JobRole


class Interests(ServiceInput):
    """списки личных и отключённых тегов для полной замены настроек интересов"""

    personal: list[str] = Field(max_length=500)
    disabled: list[str] = Field(max_length=500)


class SessionGrant(BaseModel):
    """пользователь, токен и срок действия сессии

    токен скрыт при обычном выводе объекта
    """

    user: UserData
    token: SecretStr
    expires_at: AwareDatetime


class IncomingNews(ServiceInput):
    """данные от парсера: источник, ID или ссылка, текст и дата публикации"""

    source: str = Field(min_length=1)
    external_id: str | None = None
    url: str | None = None
    title: str = Field(min_length=1)
    body: str
    published_at: AwareDatetime
    language: str = Field(default="ru", min_length=1)

    @model_validator(mode="after")
    def check_source_identity(self):
        """приводит пустые идентификаторы к None и требует внешний ID либо корректный HTTP(S)-URL"""
        self.external_id = self.external_id or None
        self.url = self.url or None
        if self.url is not None:
            self.url = str(TypeAdapter(HttpUrl).validate_python(self.url))
        if self.external_id is None and self.url is None:
            raise ValueError("external_id or url is required")
        return self


class ProfilePolicy(ServiceInput):
    """настройки расчёта интересов: веса по должностям, сила поправки по реакциям и версия правил"""

    role_weights: dict[JobRole, dict[str, Weight]] = Field(default_factory=dict)
    reaction_alpha: float = Field(default=0.2, ge=0, le=1)
    version: str = Field(default="interests-v1", min_length=1)


class AnalysisVersions(ServiceInput):
    """версии модели, промпта, отчётов, агента и поиска, входящие в ключ кеша"""

    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    report_corpus_version: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    retrieval_version: str = Field(min_length=1)


class AnalysisWork(BaseModel):
    """задание, новость и контекст компании, которые сервис подготовил для worker

    также содержит версии AI-компонентов и ключ кеша
    """

    job: JobData
    news: StoredNews
    context: ContextData
    versions: AnalysisVersions
    cache_key: str


Reaction = Literal["like", "dislike", "none"]
