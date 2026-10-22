"""API adapters for news and financial data sources mentioned in the chat."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .models import MarketQuote, NewsItem
from .normalize import normalize_date
from .article import enrich_news_items


def _require_key(api_key: Optional[str], name: str) -> str:
    if not api_key:
        raise ValueError(f"{name} requires an API key")
    return api_key


def fetch_currents_news(
    api_key: Optional[str] = None,
    language: str = "ru",
    keywords: Optional[str] = None,
    limit: int = 50,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "Currents API")
    params: Dict[str, Any] = {"apiKey": key, "language": language}
    if keywords:
        params["keywords"] = keywords
    url = "https://api.currentsapi.services/v1/latest-news"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data.get("news", [])[:limit]:
        items.append(
            NewsItem(
                source="currents",
                title=art.get("title", ""),
                text=art.get("description", ""),
                url=art.get("url", ""),
                published_at=normalize_date(art.get("published")),
                tags=[language],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_newsdata_news(
    api_key: Optional[str] = None,
    language: str = "ru",
    category: Optional[str] = None,
    limit: int = 50,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "NewsData.io")
    params: Dict[str, Any] = {"apikey": key, "language": language}
    if category:
        params["category"] = category
    url = "https://newsdata.io/api/1/news"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data.get("results", [])[:limit]:
        items.append(
            NewsItem(
                source="newsdata",
                title=art.get("title", ""),
                text=art.get("description", "") or art.get("content", ""),
                url=art.get("link", ""),
                published_at=normalize_date(art.get("pubDate")),
                tags=art.get("category") or [],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_gnews_news(
    api_key: Optional[str] = None,
    lang: str = "ru",
    query: Optional[str] = None,
    limit: int = 10,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "GNews")
    if query:
        url = "https://gnews.io/api/v4/search"
        params = {"token": key, "q": query, "lang": lang, "max": limit}
    else:
        url = "https://gnews.io/api/v4/top-headlines"
        params = {"token": key, "lang": lang, "max": limit}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data.get("articles", [])[:limit]:
        items.append(
            NewsItem(
                source="gnews",
                title=art.get("title", ""),
                text=art.get("description", ""),
                url=art.get("url", ""),
                published_at=normalize_date(art.get("publishedAt")),
                tags=[lang],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_guardian_news(
    api_key: Optional[str] = None,
    query: str = "economy",
    page_size: int = 20,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "The Guardian")
    url = "https://content.guardianapis.com/search"
    params = {"api-key": key, "q": query, "page-size": page_size, "show-fields": "trailText"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data.get("response", {}).get("results", []):
        fields = art.get("fields", {}) or {}
        items.append(
            NewsItem(
                source="guardian",
                title=art.get("webTitle", ""),
                text=fields.get("trailText", ""),
                url=art.get("webUrl", ""),
                published_at=normalize_date(art.get("webPublicationDate")),
                tags=[art.get("sectionName", "")],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_marketaux_news(
    api_key: Optional[str] = None,
    symbols: Optional[str] = None,
    limit: int = 10,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "Marketaux")
    url = "https://api.marketaux.com/v1/news/all"
    params: Dict[str, Any] = {"api_token": key, "limit": limit, "language": "ru"}
    if symbols:
        params["symbols"] = symbols
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data.get("data", [])[:limit]:
        items.append(
            NewsItem(
                source="marketaux",
                title=art.get("title", ""),
                text=art.get("description", ""),
                url=art.get("url", ""),
                published_at=normalize_date(art.get("published_at")),
                tags=art.get("entities", []) and [e.get("symbol") for e in art.get("entities", [])],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_alphavantage_news(
    api_key: Optional[str] = None,
    tickers: Optional[str] = None,
    limit: int = 50,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "Alpha Vantage")
    url = "https://www.alphavantage.co/query"
    params: Dict[str, Any] = {"function": "NEWS_SENTIMENT", "apikey": key}
    if tickers:
        params["tickers"] = tickers
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data.get("feed", [])[:limit]:
        items.append(
            NewsItem(
                source="alphavantage",
                title=art.get("title", ""),
                text=art.get("summary", ""),
                url=art.get("url", ""),
                published_at=normalize_date(art.get("time_published")),
                tags=art.get("ticker_sentiment", []) and [t.get("ticker") for t in art.get("ticker_sentiment", [])],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_finnhub_news(
    api_key: Optional[str] = None,
    category: str = "general",
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    key = _require_key(api_key, "Finnhub")
    url = "https://finnhub.io/api/v1/news"
    params = {"token": key, "category": category}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    items: List[NewsItem] = []
    for art in data or []:
        items.append(
            NewsItem(
                source="finnhub",
                title=art.get("headline", ""),
                text=art.get("summary", ""),
                url=art.get("url", ""),
                published_at=normalize_date(art.get("datetime")),
                tags=[category],
                raw=art,
            )
        )
    return enrich_news_items(items) if fetch_full_text else items


def fetch_fred_series(
    series_id: str,
    api_key: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """FRED observations as a list of dicts (variable result)."""
    key = _require_key(api_key, "FRED")
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": key, "file_type": "json", "limit": limit, "sort_order": "desc"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    return data.get("observations", [])
