"""alfa_news_parser: unified news/market parser library."""

from .aggregator import NewsAggregator
from .article import detect_language, extract_article_text, enrich_news_items, fetch_article_text
from .autonomous import (
    OPEN_RSS_FEEDS,
    fetch_autonomous_all,
    fetch_gdelt_articles,
    fetch_hackernews_top,
    fetch_newsline_stories,
    fetch_offstream_events,
    fetch_open_rss_feeds,
    fetch_reddit_json,
    fetch_unbiased_headlines,
    fetch_ursy_news,
)
from .models import MarketQuote, NewsItem
from .moex import fetch_moex_securities, fetch_moex_top_movers
from .normalize import deduplicate, normalize_date, strip_html, to_dataframe, to_plain
from .rss import (
    fetch_cbr_fx_rates,
    fetch_cbr_news,
    fetch_google_news_rss,
    fetch_rss_feed,
    fetch_tass_rss,
    fetch_vedomosti_rss,
)
from .sources import (
    GOV_SOURCES,
    INDUSTRY_MAPPING,
    INTERNATIONAL_SOURCES,
    MARKET_SOURCES,
    POLLING_INTERVALS,
    RUSSIAN_SOURCES,
    STARTER_SOURCES,
    VEDOMOSTI_RSS_CHANNELS,
)

__all__ = [
    "NewsAggregator",
    "detect_language",
    "extract_article_text",
    "enrich_news_items",
    "fetch_article_text",
    "fetch_offstream_events",
    "NewsItem",
    "MarketQuote",
    "fetch_rss_feed",
    "fetch_cbr_news",
    "fetch_vedomosti_rss",
    "fetch_tass_rss",
    "fetch_google_news_rss",
    "fetch_cbr_fx_rates",
    "fetch_moex_securities",
    "fetch_moex_top_movers",
    "normalize_date",
    "strip_html",
    "deduplicate",
    "to_plain",
    "to_dataframe",
    "OPEN_RSS_FEEDS",
    "fetch_autonomous_all",
    "fetch_open_rss_feeds",
    "fetch_hackernews_top",
    "fetch_reddit_json",
    "fetch_gdelt_articles",
    "fetch_newsline_stories",
    "fetch_unbiased_headlines",
    "fetch_ursy_news",
    "INTERNATIONAL_SOURCES",
    "RUSSIAN_SOURCES",
    "GOV_SOURCES",
    "MARKET_SOURCES",
    "INDUSTRY_MAPPING",
    "POLLING_INTERVALS",
    "STARTER_SOURCES",
    "VEDOMOSTI_RSS_CHANNELS",
]
