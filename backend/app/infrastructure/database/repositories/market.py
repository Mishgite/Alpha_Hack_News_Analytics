"""хранит снимки биржевых котировок"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.infrastructure.database.models.market import Stock, StockSnapshot
from app.schemas.market import StockQuote


class MarketRepository:
    """паттерн Repository: сохраняет котировки и читает последнюю запись каждой бумаги"""

    def __init__(self, session):
        """принимает сессию UnitOfWork"""
        self._session = session

    def save(self, quotes):
        """обновляет названия бумаг и сохраняет котировки без дублей по времени"""
        for quote in quotes:
            statement = insert(Stock).values(
                ticker=quote.ticker, board=quote.board, name=quote.name
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Stock.ticker, Stock.board],
                    set_={"name": quote.name, "updated_at": quote.captured_at},
                )
            )
            statement = insert(StockSnapshot).values(
                **quote.model_dump(exclude={"name"})
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=["ticker", "board", "as_of"],
                    set_={
                        k: v
                        for k, v in quote.model_dump(
                            exclude={"name", "ticker", "board", "as_of"}
                        ).items()
                    },
                )
            )

    def latest(self):
        """читает последнюю котировку каждой бумаги режима TQBR"""
        rows = self._session.execute(
            select(StockSnapshot, Stock.name)
            .join(Stock)
            .where(Stock.board == "TQBR")
            .distinct(StockSnapshot.ticker, StockSnapshot.board)
            .order_by(
                StockSnapshot.ticker, StockSnapshot.board, StockSnapshot.as_of.desc()
            )
        ).all()
        return [
            StockQuote(
                **{
                    name: getattr(row, name)
                    for name in StockQuote.model_fields
                    if name != "name"
                },
                name=name,
            )
            for row, name in rows
        ]
