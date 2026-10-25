"""HTTP-доступ к последнему биржевому снимку"""

from fastapi import APIRouter, Depends, Query

from app.schemas.database import UserData
from app.schemas.market import MarketOverview
from app.services.market import MarketService

from .dependencies import get_current_user

router = APIRouter(tags=["Биржа"])


def get_market_service():
    """предоставляет сервис чтения котировок без сетевого запроса к бирже"""
    return MarketService()


@router.get("/market", response_model=MarketOverview)
def overview(
    limit: int = Query(20, ge=1, le=100),
    user: UserData = Depends(get_current_user),
    service: MarketService = Depends(get_market_service),
):
    """возвращает тепловую карту, топ изменений и признак устаревания данных"""
    return service.get_overview(limit=limit)
