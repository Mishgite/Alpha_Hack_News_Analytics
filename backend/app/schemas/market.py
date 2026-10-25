"""котировки и данные для тепловой карты"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StockQuote(BaseModel):
    """разделяет цену, денежный оборот, количество бумаг и время котировки"""

    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)
    ticker: str
    board: str = "TQBR"
    name: str
    as_of: AwareDatetime
    captured_at: AwareDatetime
    price: float | None = Field(default=None, ge=0)
    previous_close: float | None = Field(default=None, ge=0)
    change_abs: float | None = None
    change_percent: float | None = None
    turnover_rub: float | None = Field(default=None, ge=0)
    volume: float | None = Field(default=None, ge=0)
    data_delay_minutes: int | None = Field(default=None, ge=0)


class MarketTile(StockQuote):
    """передаёт фронтенду размер и цвет без генерации изображения"""

    size_metric: float
    color_metric: float | None


class MarketOverview(BaseModel):
    """сообщает актуальность снимка и содержит карту с лидерами изменения цены"""

    source: str = "MOEX ISS"
    status: Literal["ready", "stale", "empty"]
    captured_at: AwareDatetime | None = None
    size_basis: Literal["turnover_rub", "equal"]
    change_basis: str = "previous_close"
    heatmap: list[MarketTile]
    top_movers: list[StockQuote]
