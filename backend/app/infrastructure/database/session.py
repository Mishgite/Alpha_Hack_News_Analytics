"""настройка пула соединений и создание сессий для отдельных операций"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.config import Settings, get_settings


def create_db_engine(settings: Settings) -> Engine:
    """создаёт движок PostgreSQL с пулом, проверкой соединений и часовым поясом UTC"""
    return create_engine(
        settings.database_url.get_secret_value(),
        # перед использованием проверяем соединение, которое мог закрыть сервер
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        connect_args={
            "connect_timeout": 5,
            "options": (
                "-c timezone=UTC "
                f"-c statement_timeout={settings.db_statement_timeout_ms} "
                f"-c lock_timeout={settings.db_lock_timeout_ms}"
            ),
        },
        hide_parameters=True,
    )


# пул общий для процесса; отдельная Session создаётся на каждый UnitOfWork
@lru_cache
def get_engine() -> Engine:
    """возвращает общий для процесса движок; создаёт его при первом обращении"""
    return create_db_engine(get_settings())


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # commit не заставляет повторно читать уже загруженные поля внутри слоя БД
    # наружу всё равно передаём DTO, а не привязанные к сессии ORM-объекты
    """фабрика объектов (Factory): задаёт общие настройки создания сессий

    каждый вызов фабрики создаёт отдельную Session для переданного движка
    """
    return sessionmaker(bind=engine, expire_on_commit=False)
