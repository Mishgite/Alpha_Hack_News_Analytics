"""сессии, выбор компании и настройки пользователя"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.schemas.api import CompanySelection, SessionResponse
from app.schemas.database import CompanyData, ProfileInputs, TagData, UserData
from app.schemas.services import Interests, Registration, UserSettings
from app.services import NewsService, ProfileService

from .dependencies import (
    get_current_user,
    get_news_service,
    get_profile_service,
    get_token,
)

router = APIRouter(tags=["Профиль"])


@router.get("/companies", response_model=list[CompanyData])
def list_companies(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    query: str = Query("", max_length=150),
    service: ProfileService = Depends(get_profile_service),
):
    """возвращает компании для демовхода, без утверждения реальных банковских прав"""
    if not request.app.state.settings.demo_enabled:
        raise HTTPException(403, "Demo company catalogue is disabled")
    return service.list_companies(limit=limit, offset=offset, query=query)


@router.post("/auth/demo", response_model=SessionResponse, status_code=201)
def create_session(
    data: Registration,
    request: Request,
    response: Response,
    service: ProfileService = Depends(get_profile_service),
):
    """создаёт демопользователя и возвращает токен для следующих запросов"""
    if not request.app.state.settings.demo_enabled:
        raise HTTPException(403, "Demo registration is disabled")
    session = service.register_demo(data)
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(
        user=session.user,
        access_token=session.token.get_secret_value(),
        expires_at=session.expires_at,
    )


@router.post("/auth/logout", status_code=204)
def logout(
    user: UserData = Depends(get_current_user),
    token: str = Depends(get_token),
    service: ProfileService = Depends(get_profile_service),
):
    """отзывает текущую сессию, после этого её токен больше не принимается"""
    service.logout(token)
    return Response(status_code=204)


@router.get("/profile", response_model=ProfileInputs)
def get_profile(
    user: UserData = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    """возвращает выбранную компанию, роль, интересы и реакции пользователя"""
    return service.get_profile(user.id)


@router.put("/profile/company", response_model=ProfileInputs)
def select_company(
    data: CompanySelection,
    request: Request,
    user: UserData = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    """меняет компанию в деморежиме и закрывает доступ к лентам прежней компании"""
    if not request.app.state.settings.demo_enabled:
        raise HTTPException(403, "Demo company selection is disabled")
    return service.switch_company(user.id, data.company_id)


@router.put("/profile/settings", response_model=UserData)
def update_settings(
    data: UserSettings,
    user: UserData = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    """заменяет город и должность текущего пользователя"""
    return service.update_settings(user.id, data)


@router.put("/profile/interests", response_model=ProfileInputs)
def update_interests(
    data: Interests,
    user: UserData = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    """заменяет списки личных и отключённых тем, не меняя темы компании"""
    return service.set_interests(user.id, data)


@router.get("/tags", response_model=list[TagData])
def list_tags(
    user: UserData = Depends(get_current_user),
    service: NewsService = Depends(get_news_service),
):
    """возвращает доступные темы для выбора интересов"""
    return service.list_tags()


@router.get("/profile/context")
def get_context(
    user: UserData = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    """возвращает известные признаки компании и сведения об их происхождении"""
    return service.get_context(user.id)


@router.get("/profile/priorities")
def get_priorities(
    user: UserData = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
):
    """возвращает эффективные веса тем с учётом роли, интересов и реакций"""
    from app.services.profiles import build_profile

    return build_profile(service.get_profile(user.id), service.policy)
