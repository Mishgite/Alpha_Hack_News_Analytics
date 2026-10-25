"""настройки фоновых циклов и источников новостей"""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class WorkerSource(BaseModel):
    """задаёт RSS-ленту и предел числа записей за одну загрузку"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1)
    url: HttpUrl
    limit: int = Field(default=30, ge=1, le=500)
    full_text: bool = False


class WorkerSettings(BaseModel):
    """ограничивает частоту запросов, размер порции и время одного AI-разбора"""

    model_config = ConfigDict(extra="forbid")
    sources: list[WorkerSource] = Field(
        default_factory=lambda: [
            WorkerSource(code="cbr", url="https://www.cbr.ru/rss/RssPress"),
        ]
    )
    fetch_interval: float = Field(default=900, gt=0, allow_inf_nan=False)
    tagging_interval: float = Field(default=300, gt=0, allow_inf_nan=False)
    analysis_interval: float = Field(default=5, gt=0, allow_inf_nan=False)
    tagging_batch: int = Field(default=1, ge=1, le=100)
    analysis_timeout: int = Field(default=900, ge=1, le=1800)

    profile_batch: int = Field(default=1, ge=1, le=10)
    profile_interval: float = Field(default=120, gt=0, allow_inf_nan=False)
    market_enabled: bool = True
    market_interval: float = Field(default=900, gt=0, allow_inf_nan=False)
    reports_directory: str | None = None

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, sources):
        """не позволяет запускать два цикла для одного кода источника"""
        if len({source.code for source in sources}) != len(sources):
            raise ValueError("Source codes must be unique")
        return sources
