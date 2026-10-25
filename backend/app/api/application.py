"""создание приложения, настройки браузерных запросов и обработка ошибок"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from . import feed, insights, market, profiles

logger = logging.getLogger(__name__)


class ApiSettings(BaseSettings):
    """читает настройки деморежима и разрешённые адреса фронтенда из app/.env"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8-sig",
        env_prefix="API_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    demo_enabled: bool = True
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


async def handle_service_error(request: Request, error: Exception) -> JSONResponse:
    """переводит ошибки сервисов в HTTP-ответы без SQL и параметров подключения"""
    if isinstance(error, ValidationError):
        status, detail = 500, "Invalid internal data"
    elif isinstance(error, IntegrityError):
        status, detail = 409, "Data conflict"
    elif isinstance(error, (OperationalError, PoolTimeout)):
        status, detail = 503, "Database unavailable"
    elif isinstance(error, SQLAlchemyError):
        status, detail = 500, "Database operation failed"
    elif isinstance(error, TimeoutError):
        status, detail = 504, "Processing timed out"
    elif isinstance(error, RuntimeError):
        status, detail = 503, "Processing service unavailable"
    elif isinstance(error, PermissionError):
        status, detail = 403, "Access denied"
    elif type(error) is LookupError:
        status, detail = 404, str(error)
    elif type(error) is ValueError:
        status, detail = 400, str(error)
    else:
        status, detail = 500, "Internal server error"
    if status >= 500:
        logger.error(
            "%s %s: %s", request.method, request.url.path, type(error).__name__
        )
    return JSONResponse(status_code=status, content={"detail": detail})


async def handle_validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    """возвращает поле и причину ошибки без копирования исходного тела запроса"""
    details = [
        {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """собирает маршруты API и обработчики ошибок без подключения к БД при импорте"""
    settings = settings if settings is not None else ApiSettings()
    application = FastAPI(
        title="Альфа: новостная аналитика",
        version="0.1.0",
        description=(
            "Демовход, профиль, лента и реакции. "
            "Ранжирование по формуле, AI-разбор выполняет отдельный worker."
        ),
    )
    application.state.settings = settings

    @application.middleware("http")
    async def handle_unexpected_error(request, call_next):
        """возвращает JSON при непредвиденном сбое до отправки заголовков ответа"""
        try:
            return await call_next(request)
        except Exception as error:
            return await handle_service_error(request, error)

    # CORS оборачивает обработчик, чтобы браузер мог прочитать и ответ с ошибкой
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )
    for error_type in (
        ValueError,
        LookupError,
        PermissionError,
        SQLAlchemyError,
        ValidationError,
        RuntimeError,
        TimeoutError,
    ):
        application.add_exception_handler(error_type, handle_service_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    for router in (profiles.router, feed.router, insights.router, market.router):
        application.include_router(router, prefix="/api")

    @application.get("/health", tags=["Состояние"])
    def health():
        """подтверждает работу HTTP-сервера, состояние БД этот метод не проверяет"""
        return {
            "status": "ok",
            "ranking": "formula-v1",
            "ai_analysis": "worker_required",
        }

    return application


app = create_app()
