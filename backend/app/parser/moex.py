"""MOEX ISS adapters."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .models import MarketQuote
from .normalize import normalize_date


MOEX_BASE = "https://iss.moex.com/iss"


def fetch_moex_securities(
    engine: str = "stock",
    market: str = "shares",
    board: str = "TQBR",
    limit: int = 100,
) -> List[MarketQuote]:
    """Fetch MOEX securities snapshot and normalize to MarketQuote list."""
    url = f"{MOEX_BASE}/engines/{engine}/markets/{market}/boards/{board}/securities.json"
    params = {"iss.meta": "off", "iss.only": "securities,marketdata", "limit": limit}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    sec_cols = data.get("securities", {}).get("columns", [])
    sec_rows = data.get("securities", {}).get("data", [])
    md_cols = data.get("marketdata", {}).get("columns", [])
    md_rows = data.get("marketdata", {}).get("data", [])

    sec_map = {row[sec_cols.index("SECID")]: row for row in sec_rows} if "SECID" in sec_cols else {}
    md_by_sec = {}
    for row in md_rows:
        if "SECID" in md_cols:
            md_by_sec[row[md_cols.index("SECID")]] = row

    result: List[MarketQuote] = []
    for secid, srow in sec_map.items():
        mrow = md_by_sec.get(secid, [])
        def g(cols, row, name, default=None):
            if not row or name not in cols:
                return default
            idx = cols.index(name)
            return row[idx] if idx < len(row) else default

        price = g(md_cols, mrow, "LAST")
        change = g(md_cols, mrow, "CHANGE")
        change_pct = g(md_cols, mrow, "LASTCHANGEPRCNT")
        volume = g(md_cols, mrow, "VOLTODAY") or g(md_cols, mrow, "VALTODAY")
        updated = g(md_cols, mrow, "SYSTIME") or g(md_cols, mrow, "UPDATETIME")
        name = g(sec_cols, srow, "SHORTNAME") or g(sec_cols, srow, "SECNAME") or secid
        result.append(
            MarketQuote(
                ticker=secid,
                name=name,
                price=float(price) if price is not None else None,
                change=float(change) if change is not None else None,
                change_percent=float(change_pct) if change_pct is not None else None,
                volume=float(volume) if volume is not None else None,
                updated_at=normalize_date(updated),
                source="moex",
                raw={"security": dict(zip(sec_cols, srow)), "marketdata": dict(zip(md_cols, mrow)) if mrow else {}},
            )
        )
    return result


def fetch_moex_top_movers(limit: int = 20) -> List[MarketQuote]:
    """Return top movers by absolute change percent."""
    quotes = fetch_moex_securities(limit=500)
    quotes_sorted = sorted(quotes, key=lambda q: abs(q.change_percent or 0), reverse=True)
    return quotes_sorted[:limit]


def fetch_moex_index(index: str = "IMOEX") -> Optional[Dict[str, Any]]:
    url = f"{MOEX_BASE}/statistics/engines/stock/markets/index/analytics/{index}.json"
    params = {"iss.meta": "off"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    return data
