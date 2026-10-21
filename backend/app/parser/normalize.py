"""Normalization helpers shared by all adapters."""

from __future__ import annotations

import hashlib
import re

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None
from datetime import datetime, timezone
from html import unescape
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, List

from .models import NewsItem


def normalize_date(value: Any) -> str:
    """Convert various date formats to an ISO-8601 UTC string."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:
            v = v / 1000.0
        try:
            dt = datetime.fromtimestamp(v, tz=timezone.utc)
            return dt.isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    # GDELT seendate format: 20261021T120000Z
    try:
        dt = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        pass
    # RFC-822 (RSS)
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    # ISO-8601
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    return text


def deduplicate(items: Iterable[NewsItem]) -> List[NewsItem]:
    """Remove duplicate news by (source, title, url)."""
    seen: set[str] = set()
    result: List[NewsItem] = []
    for item in items:
        key = hashlib.sha256(
            f"{item.source}|{item.title}|{item.url}".encode("utf-8")
        ).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_plain(items: Iterable[NewsItem]) -> List[dict]:
    return [i.to_dict() for i in items]


def to_dataframe(items: Iterable[NewsItem]):
    if pd is None:
        raise RuntimeError("pandas is not installed")
    return pd.DataFrame([i.to_dict() for i in items])
