"""Autonomous (no API key) parsers: open RSS feeds and open JSON APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

import httpx

from .models import NewsItem
from .normalize import normalize_date, strip_html
from .article import enrich_news_items
from .rss import fetch_rss_feed


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Open RSS feeds (no key, no signup)
# ---------------------------------------------------------------------------

OPEN_RSS_FEEDS: Dict[str, str] = {
    "bbc_top": "https://feeds.bbci.co.uk/news/rss.xml",
    "bbc_world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_tech": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "bbc_business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "guardian_world": "https://www.theguardian.com/world/rss",
    "guardian_tech": "https://www.theguardian.com/uk/technology/rss",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "sky_news": "https://feeds.skynews.com/feeds/rss/home.xml",
    "npr": "https://feeds.npr.org/1001/rss.xml",
    "cbs": "https://www.cbsnews.com/latest/rss/main",
    "wsj_world": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "euronews": "https://www.euronews.com/rss",
    "lemonde_en": "https://www.lemonde.fr/en/rss/une.xml",
    "spiegel_intl": "https://www.spiegel.de/international/index.rss",
    "times_of_india": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "ndtv": "https://feeds.feedburner.com/ndtvnews-top-stories",
    "abc_australia": "https://www.abc.net.au/news/feed/51120/rss.xml",
    "un_news": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
    "techcrunch": "https://techcrunch.com/feed/",
    "ars_technica": "https://feeds.arstechnica.com/arstechnica/index",
    "the_verge": "https://www.theverge.com/rss/index.xml",
    "engadget": "https://www.engadget.com/rss.xml",
    "hacker_news": "https://hnrss.org/frontpage",
    "nyt_home": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "dw_english": "https://rss.dw.com/xml/rss-en-all",
    "fox_latest": "https://moxie.foxnews.com/google-publisher/latest.xml",
    "cnbc": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
}


def fetch_open_rss_feeds(
    feeds: Optional[List[str]] = None,
    timeout: float = 20.0,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """Fetch any subset of OPEN_RSS_FEEDS (or all of them) autonomously."""
    selected = feeds or list(OPEN_RSS_FEEDS.keys())
    items: List[NewsItem] = []
    for name in selected:
        url = OPEN_RSS_FEEDS.get(name)
        if not url:
            continue
        try:
            items.extend(fetch_rss_feed(url, source=name, timeout=timeout, fetch_full_text=False))
        except Exception as exc:
            logger.warning("Could not parse RSS source %s (%s)", name, type(exc).__name__)
            continue
    return enrich_news_items(items) if fetch_full_text else items


# ---------------------------------------------------------------------------
# Open JSON APIs (no key)
# ---------------------------------------------------------------------------


def fetch_hackernews_top(
    limit: int = 30,
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """Hacker News Firebase API (no key)."""
    items: List[NewsItem] = []
    try:
        with httpx.Client(timeout=20.0) as client:
            ids = client.get("https://hacker-news.firebaseio.com/v0/topstories.json").json()[:limit]
            for sid in ids:
                try:
                    d = client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json").json()
                except Exception:
                    continue
                if not d or d.get("type") != "story":
                    continue
                items.append(
                    NewsItem(
                        source="hackernews",
                        title=d.get("title", ""),
                        text=d.get("text", "") or "",
                        url=d.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                        published_at=normalize_date(d.get("time")),
                        tags=["hackernews"],
                        raw=d,
                    )
                )
    except Exception:
        pass
    return enrich_news_items(items) if fetch_full_text else items


def fetch_reddit_json(
    subreddit: str = "news",
    limit: int = 25,
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """Reddit public JSON endpoint (no key)."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    items: List[NewsItem] = []
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": "alfa-news-parser/0.1"}) as client:
            data = client.get(url, params={"limit": limit}).json()
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            items.append(
                NewsItem(
                    source=f"reddit_{subreddit}",
                    title=d.get("title", ""),
                    text=strip_html(d.get("selftext", "")),
                    url="https://www.reddit.com" + d.get("permalink", ""),
                    published_at=normalize_date(d.get("created_utc")),
                    tags=[subreddit],
                    raw=d,
                )
            )
    except Exception:
        pass
    return enrich_news_items(items) if fetch_full_text else items


def fetch_gdelt_articles(
    query: str = "economy",
    limit: int = 25,
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """GDELT Doc API (no key)."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": limit,
        "format": "json",
        "sort": "datedesc",
    }
    items: List[NewsItem] = []
    try:
        with httpx.Client(timeout=30.0) as client:
            data = client.get(url, params=params).json()
        for art in data.get("articles", [])[:limit]:
            items.append(
                NewsItem(
                    source="gdelt",
                    title=art.get("title", ""),
                    text="",
                    url=art.get("url", ""),
                    published_at=normalize_date(art.get("seendate")),
                    tags=[query],
                    raw=art,
                )
            )
    except Exception:
        pass
    return enrich_news_items(items) if fetch_full_text else items


def fetch_offstream_events(*, fetch_full_text: bool = True) -> List[NewsItem]:
    """Fetch Offstream current-events JSON while the HTTP client is still open.

    A failed daily document is logged and skipped; a failed index is logged and
    returns an empty list. HTTP status codes are checked instead of accepting
    error pages as JSON.
    """
    items: List[NewsItem] = []
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            index_response = client.get("https://offstream.news/index.json")
            index_response.raise_for_status()
            data = index_response.json()
            days = data if isinstance(data, list) else data.get("items", [])

            # IMPORTANT: every request in the loop is inside this `with` block.
            for day in (days or [])[:5]:
                if not isinstance(day, dict):
                    logger.warning("Skipping malformed Offstream day record: %r", day)
                    continue
                link = day.get("url") or day.get("link")
                if not link:
                    logger.warning("Skipping Offstream day without url/link: %r", day)
                    continue
                json_url = link[:-5] + ".json" if link.endswith(".html") else link
                try:
                    response = client.get(json_url)
                    response.raise_for_status()
                    ddata = response.json()
                except Exception as exc:
                    logger.warning("Offstream day request failed for %s: %s", json_url, exc)
                    continue

                events = ddata.get("items", []) if isinstance(ddata, dict) else []
                if not isinstance(events, list):
                    logger.warning("Unexpected Offstream items payload for %s", json_url)
                    continue
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    description = (
                        ev.get("text")
                        or ev.get("content")
                        or ev.get("description")
                        or ev.get("body")
                        or ""
                    )
                    items.append(
                        NewsItem(
                            source="offstream",
                            title=str(ev.get("title", "") or ""),
                            text=strip_html(description),
                            url=str(ev.get("url", "") or ""),
                            published_at=normalize_date(ev.get("date")),
                            tags=["wikipedia_current_events"],
                            raw=ev,
                        )
                    )
    except Exception as exc:
        logger.exception("Could not fetch Offstream index/events: %s", exc)
    return enrich_news_items(items) if fetch_full_text else items


def fetch_newsline_stories(
    limit: int = 60,
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """Newsline API (no key)."""
    items: List[NewsItem] = []
    try:
        with httpx.Client(timeout=20.0) as client:
            data = client.get("https://news.heyitsmejosh.com/api/stories", params={"view": "latest", "limit": limit}).json()
        for d in data.get("latest", []):
            items.append(
                NewsItem(
                    source="newsline",
                    title=d.get("title", ""),
                    text="",
                    url=d.get("link", ""),
                    published_at=normalize_date(d.get("ts")),
                    tags=[d.get("outlet", "")],
                    raw=d,
                )
            )
    except Exception:
        pass
    return enrich_news_items(items) if fetch_full_text else items


def fetch_unbiased_headlines(
    limit: int = 20,
    category: Optional[str] = None,
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """Unbiased Headlines public API (no key)."""
    items: List[NewsItem] = []
    params: Dict[str, Any] = {"limit": limit}
    if category:
        params["category"] = category
    try:
        with httpx.Client(timeout=20.0) as client:
            data = client.get("https://unbiasedheadlines.com/api/public/v1/articles", params=params).json()
        for d in data.get("articles", []) or data.get("data", []) or []:
            items.append(
                NewsItem(
                    source="unbiased_headlines",
                    title=d.get("title", ""),
                    text=d.get("summary", "") or d.get("description", ""),
                    url=d.get("canonical_url", "") or d.get("url", ""),
                    published_at=normalize_date(d.get("published_at") or d.get("date")),
                    tags=[d.get("category", "")],
                    raw=d,
                )
            )
    except Exception:
        pass
    return enrich_news_items(items) if fetch_full_text else items


def fetch_ursy_news(
    limit: int = 20,
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """URSY.news API (no key)."""
    items: List[NewsItem] = []
    try:
        with httpx.Client(timeout=20.0) as client:
            data = client.get("https://ursy.news/api/v1/headlines", params={"limit": limit}).json()
        for d in (data if isinstance(data, list) else data.get("headlines", []) or data.get("data", [])):
            items.append(
                NewsItem(
                    source="ursy",
                    title=d.get("title", ""),
                    text=d.get("excerpt", "") or d.get("description", ""),
                    url=d.get("original_url", "") or d.get("url", ""),
                    published_at=normalize_date(d.get("published_at")),
                    tags=d.get("topics", []) or [],
                    raw=d,
                )
            )
    except Exception:
        pass
    return enrich_news_items(items) if fetch_full_text else items


def fetch_google_news_rss_autonomous(
    query: str,
    lang: str = "en",
    country: str = "US",
    *,
    fetch_full_text: bool = True,
) -> List[NewsItem]:
    """Google News RSS (no key)."""
    from .rss import fetch_google_news_rss

    return fetch_google_news_rss(query, lang=lang, country=country, fetch_full_text=fetch_full_text)


def fetch_autonomous_all(
    include_rss: bool = True,
    rss_feeds: Optional[List[str]] = None,
    include_apis: bool = True,
    google_queries: Optional[List[str]] = None,
    gdelt_query: str = "economy",
) -> List[NewsItem]:
    """Aggregate all autonomous (no-key) sources into one variable."""
    items: List[NewsItem] = []
    if include_rss:
        items.extend(fetch_open_rss_feeds(rss_feeds, fetch_full_text=False))
        for q in (google_queries or []):
            items.extend(fetch_google_news_rss_autonomous(q, fetch_full_text=False))
    if include_apis:
        items.extend(fetch_hackernews_top(fetch_full_text=False))
        items.extend(fetch_reddit_json("news", fetch_full_text=False))
        items.extend(fetch_reddit_json("worldnews", fetch_full_text=False))
        items.extend(fetch_gdelt_articles(gdelt_query, fetch_full_text=False))
        items.extend(fetch_offstream_events(fetch_full_text=False))
        items.extend(fetch_newsline_stories(fetch_full_text=False))
        items.extend(fetch_unbiased_headlines(fetch_full_text=False))
        try:
            items.extend(fetch_ursy_news(fetch_full_text=False))
        except Exception:
            pass
    # dedup
    from .normalize import deduplicate

    return deduplicate(enrich_news_items(items))
