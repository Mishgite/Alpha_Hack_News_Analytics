from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, UUIDPrimaryKey, timestamp


class Stock(Base):
    """биржевой инструмент; один тикер на разных режимах торгов считается разными записями"""

    __tablename__ = "stocks"
    ticker: Mapped[str] = mapped_column(primary_key=True)
    board: Mapped[str] = mapped_column(primary_key=True)
    isin: Mapped[str | None]
    name: Mapped[str]
    sector: Mapped[str | None]
    updated_at: Mapped[datetime] = timestamp(
        server_default=func.now(), onupdate=func.now()
    )


class StockSnapshot(UUIDPrimaryKey, Base):
    """котировка на указанное время; время данных и время получения сохраняются отдельно"""

    __tablename__ = "stock_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["ticker", "board"], ["stocks.ticker", "stocks.board"]),
        UniqueConstraint("ticker", "board", "as_of"),
        CheckConstraint("data_delay_minutes >= 0", name="nonnegative_delay"),
    )
    ticker: Mapped[str]
    board: Mapped[str]
    captured_at: Mapped[datetime] = timestamp(server_default=func.now())
    as_of: Mapped[datetime] = timestamp()
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    change_abs: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    change_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    turnover_rub: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    market_cap_rub: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    data_delay_minutes: Mapped[int | None]
