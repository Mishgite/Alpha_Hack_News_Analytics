"""Data models returned by the parser as plain Python variables."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class NewsItem:
    """Unified news record produced by every adapter."""

    source: str
    title: str
    text: str = ""
    url: str = ""
    published_at: str = ""
    tags: List[str] = field(default_factory=list)
    language: str = "und"
    raw: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        # Do not label every article Russian just because a source omitted language.
        # Short summaries are not sufficient for reliable detection, so "und" is
        # retained until the full article body is extracted.
        if not self.language or self.language.lower() in {"auto", "und"}:
            from .article import detect_language

            self.language = detect_language(self.text or self.title, fallback="und")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


@dataclass
class MarketQuote:
    """Unified market quote record (stocks, FX, commodities)."""

    ticker: str
    name: str = ""
    price: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[float] = None
    updated_at: str = ""
    source: str = "moex"
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
