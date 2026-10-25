"""обновляет MOEX и формирует независимый от новостей биржевой обзор"""

from datetime import UTC, datetime, timedelta, timezone

from app.infrastructure.database.uow import UnitOfWork
from app.parser.moex import fetch_moex_securities
from app.schemas.market import MarketOverview, MarketTile, StockQuote


class MarketService:
    """паттерн Service Layer: преобразует ответ источника и отдаёт последний сохранённый снимок"""

    def __init__(self, *, uow_factory=UnitOfWork, fetcher=fetch_moex_securities):
        """принимает фабрику транзакций и заменяемый источник котировок"""
        self._uow, self.fetcher = uow_factory, fetcher

    def refresh(self):
        """получает котировки вне транзакции и сохраняет только записи с известным временем данных"""
        raw = self.fetcher(limit=500)[:500]
        now = datetime.now(UTC)
        quotes = []
        for item in raw:
            security = item.raw.get("security", {})
            data = item.raw.get("marketdata", {})
            timestamp = data.get("SYSTIME")
            if not timestamp:
                continue
            as_of = datetime.fromisoformat(timestamp)
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone(timedelta(hours=3)))
            as_of = as_of.astimezone(UTC)
            previous = security.get("PREVPRICE")
            price = data.get("LAST")
            difference = (
                price - previous
                if price is not None and previous is not None and previous > 0
                else None
            )
            quotes.append(
                StockQuote(
                    ticker=item.ticker,
                    board="TQBR",
                    name=item.name,
                    as_of=as_of,
                    captured_at=now,
                    price=price,
                    previous_close=previous,
                    change_abs=difference,
                    change_percent=100 * difference / previous
                    if difference is not None
                    else None,
                    turnover_rub=data.get("VALTODAY"),
                    volume=data.get("VOLTODAY"),
                    data_delay_minutes=None,
                )
            )
        if not quotes:
            raise RuntimeError("MOEX returned no dated quotes")
        with self._uow() as db:
            db.market.save(quotes)
            db.runtime.save("market", {"status": "ready", "count": len(quotes)})
            db.commit()
        return len(quotes)

    def get_overview(self, *, limit=20):
        """строит карту и топ по модулю изменения, старые котировки помечает как stale"""
        if not 1 <= limit <= 100:
            raise ValueError("Invalid market limit")
        with self._uow() as db:
            quotes = db.market.latest()
            state = db.runtime.get("market")
        if not quotes:
            return MarketOverview(
                status="empty", size_basis="equal", heatmap=[], top_movers=[]
            )
        captured = max(q.captured_at for q in quotes)
        # старые бумаги исключаются из свежего среза, чтобы карта не смешивала разные загрузки
        quotes = [q for q in quotes if q.captured_at == captured]
        stale = (
            datetime.now(UTC) - min(q.as_of for q in quotes)
        ).total_seconds() > 1800
        stale = stale or (
            state is not None and state["value"].get("status") == "failed"
        )
        turnover = all(q.turnover_rub is not None for q in quotes) and any(
            q.turnover_rub > 0 for q in quotes
        )
        tiles = [
            MarketTile(
                **q.model_dump(),
                size_metric=q.turnover_rub if turnover else 1,
                color_metric=q.change_percent,
            )
            for q in quotes
        ]
        movers = sorted(
            [q for q in quotes if q.change_percent is not None],
            key=lambda q: (-abs(q.change_percent), q.ticker),
        )[:limit]
        return MarketOverview(
            status="stale" if stale else "ready",
            captured_at=captured,
            size_basis="turnover_rub" if turnover else "equal",
            heatmap=tiles,
            top_movers=movers,
        )
