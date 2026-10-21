"""RSS adapters. All functions return Python variables (lists of NewsItem)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import feedparser
import httpx

from .models import NewsItem
from .normalize import normalize_date, strip_html


def fetch_rss_feed(
    url: str,
    source: str,
    tags: Optional[List[str]] = None,
    timeout: float = 20.0,
) -> List[NewsItem]:
    """Fetch and normalize a generic RSS/Atom feed into a list of NewsItem."""
    tags = tags or []
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content = resp.text
    except Exception:
        feed = feedparser.parse(url)
        content = None
        parsed = feed
    else:
        parsed = feedparser.parse(content)

    items: List[NewsItem] = []
    for entry in getattr(parsed, "entries", []) or []:
        if isinstance(entry, dict):
            _text = (
                entry.get("summary")
                or entry.get("description")
                or ""
            )
            if not _text and entry.get("content"):
                try:
                    _text = entry["content"][0].get("value", "")
                except Exception:
                    _text = ""
            _title = entry.get("title", "")
            _url = entry.get("link", "")
            _published = entry.get("published", entry.get("updated", ""))
        else:
            _text = getattr(entry, "summary", "") or getattr(entry, "description", "")
            _title = getattr(entry, "title", "")
            _url = getattr(entry, "link", "")
            _published = getattr(entry, "published", getattr(entry, "updated", ""))

        items.append(
            NewsItem(
                source=source,
                title=_title,
                text=strip_html(_text),
                url=_url,
                published_at=normalize_date(_published),
                tags=list(tags),
                raw=dict(entry) if isinstance(entry, dict) else None,
            )
        )
    return items


def fetch_cbr_news() -> List[NewsItem]:
    """Bank of Russia RSS (official)."""
    return fetch_rss_feed("https://www.cbr.ru/rss/RssPress", source="cbr", tags=["macro", "regulation"])


def fetch_vedomosti_rss(url: str, category: str = "all") -> List[NewsItem]:
    """Vedomosti RSS (category URLs from the official RSS catalog)."""
    return fetch_rss_feed(url, source="vedomosti", tags=[category])


def fetch_tass_rss(url: str) -> List[NewsItem]:
    """TASS public RSS."""
    return fetch_rss_feed(url, source="tass")


def fetch_google_news_rss(query: str, lang: str = "ru", country: str = "RU") -> List[NewsItem]:
    """Google News RSS search by keyword."""
    url = (
        f"https://news.google.com/rss/search?q={query.replace(' ', '+')}"
        f"&hl={lang}&gl={country}&ceid={country}:{lang}"
    )
    return fetch_rss_feed(url, source="google_news", tags=[query])


CBR_FX_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


def fetch_cbr_fx_rates() -> List[Dict[str, Any]]:
    """Official CBR FX rates as a list of dicts (variable result)."""
    import xml.etree.ElementTree as ET

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get(CBR_FX_URL)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

    result: List[Dict[str, Any]] = []
    for valute in root.findall("Valute"):
        result.append(
            {
                "num_code": valute.findtext("NumCode", default=""),
                "char_code": valute.findtext("CharCode", default=""),
                "nominal": int(valute.findtext("Nominal", default="1")),
                "name": valute.findtext("Name", default=""),
                "value": float(valute.findtext("Value", default="0").replace(",", ".")),
                "vunit_rate": float(valute.findtext("VunitRate", default="0").replace(",", ".")),
            }
        )
    return result
