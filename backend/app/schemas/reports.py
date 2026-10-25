"""проверяет документы и фрагменты перед загрузкой в поиск"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ReportPart(BaseModel):
    """сохраняет текст вместе с номером страницы и сведениями о распознавании"""

    model_config = ConfigDict(extra="forbid")
    page_num: int = Field(ge=1)
    chunk_no: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=12000)
    source_span_json: dict[str, JsonValue] = Field(default_factory=dict)


class ReportInput(BaseModel):
    """содержит проверяемую версию документа без пути к локальным файлам"""

    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=1000)
    file_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    report_date: date | None = None
    source_url: str | None = None
    parts: list[ReportPart] = Field(min_length=1, max_length=10000)
