"""Normalization helpers shared by all adapters."""

from __future__ import annotations

import hashlib
import re

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import urldefrag

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
            dt = datetime.fromtimestamp(v, tz=UTC)
            return dt.isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    text = str(value).strip()
    # GDELT seendate format: 20261021T120000Z
    try:
        dt = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        return dt.isoformat()
    except ValueError:
        pass
    # RFC-822 (RSS)
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        pass
    # ISO-8601
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    except ValueError:
        pass
    return text


def deduplicate(items: Iterable[NewsItem]) -> list[NewsItem]:
    """убирает повторы ссылки внутри порции, изменение заголовка не создаёт новый материал"""
    seen: set[str] = set()
    result: list[NewsItem] = []
    for item in items:
        identity = (
            urldefrag(item.url.strip()).url
            if item.url
            else f"{item.source}|{item.title}|{item.text}"
        )
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
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


def to_plain(items: Iterable[NewsItem]) -> list[dict]:
    return [i.to_dict() for i in items]


def to_dataframe(items: Iterable[NewsItem]):
    if pd is None:
        raise RuntimeError("pandas is not installed")
    return pd.DataFrame([i.to_dict() for i in items])
