"""Data models returned by the parser as plain Python variables."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class NewsItem:
    """Unified news record produced by every adapter."""

    source: str
    title: str
    text: str = ""
    url: str = ""
    published_at: str = ""
    tags: list[str] = field(default_factory=list)
    language: str = "und"
    raw: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Do not label every article Russian just because a source omitted language.
        # Short summaries are not sufficient for reliable detection, so "und" is
        # retained until the full article body is extracted.
        if not self.language or self.language.lower() in {"auto", "und"}:
            from .article import detect_language

            self.language = detect_language(self.text or self.title, fallback="und")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d

    def to_incoming_news(self):
        """преобразует результат парсера в схему сервиса, проверяет дату и ссылку"""
        from app.schemas.services import IncomingNews

        return IncomingNews(
            source=self.source,
            title=self.title,
            body=self.text,
            url=self.url or None,
            published_at=self.published_at,
            language=self.language or "und",
        )


@dataclass
class MarketQuote:
    """Unified market quote record (stocks, FX, commodities)."""

    ticker: str
    name: str = ""
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    updated_at: str = ""
    source: str = "moex"
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()
