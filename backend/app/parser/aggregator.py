"""High-level aggregator that returns results as Python variables."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .api import (
    fetch_alphavantage_news,
    fetch_currents_news,
    fetch_finnhub_news,
    fetch_gnews_news,
    fetch_guardian_news,
    fetch_marketaux_news,
    fetch_newsdata_news,
)
from .models import MarketQuote, NewsItem
from .moex import fetch_moex_top_movers, fetch_moex_securities
from .normalize import deduplicate
from .article import enrich_news_items
from .rss import (
    fetch_cbr_news,
    fetch_google_news_rss,
    fetch_rss_feed,
)
from .autonomous import fetch_autonomous_all
from .sources import (
    GOV_SOURCES,
    INDUSTRY_MAPPING,
    INTERNATIONAL_SOURCES,
    MARKET_SOURCES,
    POLLING_INTERVALS,
    RUSSIAN_SOURCES,
    STARTER_SOURCES,
)


class NewsAggregator:
    """Unified parser facade.

    Usage:
        agg = NewsAggregator(api_keys={"currents": "..."})
        news = agg.fetch_news()          # variable: list[NewsItem]
        market = agg.fetch_market()      # variable: list[MarketQuote]
        fx = agg.fetch_cbr_fx()         # variable: list[dict]
    """

    def __init__(self, api_keys: Optional[Dict[str, str]] = None):
        self.api_keys = api_keys or {}
        self.sources = {
            "international": INTERNATIONAL_SOURCES,
            "russian": RUSSIAN_SOURCES,
            "government": GOV_SOURCES,
            "market": MARKET_SOURCES,
            "industry_mapping": INDUSTRY_MAPPING,
            "polling_intervals": POLLING_INTERVALS,
            "starter": STARTER_SOURCES,
        }

    def fetch_news(
        self,
        include_rss: bool = True,
        include_api: bool = True,
        google_queries: Optional[List[str]] = None,
        limit_per_source: int = 50,
        dedup: bool = True,
    ) -> List[NewsItem]:
        """Return a single list variable with normalized news from all adapters."""
        items: List[NewsItem] = []

        if include_rss:
            try:
                items.extend(fetch_cbr_news(fetch_full_text=False))
            except Exception:
                pass
            for q in (google_queries or []):
                try:
                    items.extend(fetch_google_news_rss(q, fetch_full_text=False))
                except Exception:
                    pass

        if include_api:
            key_map = {
                "currents": ("currents", fetch_currents_news),
                "newsdata": ("newsdata", fetch_newsdata_news),
                "gnews": ("gnews", fetch_gnews_news),
                "guardian": ("guardian", fetch_guardian_news),
                "marketaux": ("marketaux", fetch_marketaux_news),
                "alphavantage": ("alphavantage", fetch_alphavantage_news),
                "finnhub": ("finnhub", fetch_finnhub_news),
            }
            for name, (src, fn) in key_map.items():
                api_key = self.api_keys.get(name)
                if not api_key:
                    continue
                try:
                    items.extend(fn(api_key=api_key, fetch_full_text=False)[:limit_per_source])
                except Exception:
                    continue

        # Retrieve original article bodies in one parallel batch instead of waiting
        # serially for every API/RSS adapter to finish extracting its articles.
        items = enrich_news_items(items)
        if dedup:
            items = deduplicate(items)
        return items

    def fetch_market(self, top_movers: bool = True, limit: int = 20) -> List[MarketQuote]:
        """Return market quotes as a list variable."""
        if top_movers:
            return fetch_moex_top_movers(limit=limit)
        return fetch_moex_securities(limit=limit * 10)

    def fetch_cbr_fx(self) -> List[Dict[str, Any]]:
        from .rss import fetch_cbr_fx_rates

        return fetch_cbr_fx_rates()

    def fetch_rss(self, url: str, source: str, tags: Optional[List[str]] = None) -> List[NewsItem]:
        return fetch_rss_feed(url, source=source, tags=tags)

    def fetch_autonomous_news(
        self,
        include_rss: bool = True,
        rss_feeds: Optional[List[str]] = None,
        include_apis: bool = True,
        google_queries: Optional[List[str]] = None,
        gdelt_query: str = "economy",
        dedup: bool = True,
    ) -> List[NewsItem]:
        """Autonomous (no API key) aggregation into a single Python variable."""
        items = fetch_autonomous_all(
            include_rss=include_rss,
            rss_feeds=rss_feeds,
            include_apis=include_apis,
            google_queries=google_queries,
            gdelt_query=gdelt_query,
        )
        if dedup:
            items = deduplicate(items)
        return items

    def as_variables(self) -> Dict[str, Any]:
        """Return all static datasets as named Python variables."""
        return {
            "international_sources": INTERNATIONAL_SOURCES,
            "russian_sources": RUSSIAN_SOURCES,
            "gov_sources": GOV_SOURCES,
            "market_sources": MARKET_SOURCES,
            "industry_mapping": INDUSTRY_MAPPING,
            "polling_intervals": POLLING_INTERVALS,
            "starter_sources": STARTER_SOURCES,
        }
