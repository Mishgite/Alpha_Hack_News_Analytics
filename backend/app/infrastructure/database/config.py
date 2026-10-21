"""чтение параметров подключения из app/.env; соединение здесь не открывается"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# путь считаем от файла, чтобы .env находился независимо от рабочей папки запуска
APP_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    # пароль в строке подключения скрывается при обычном выводе настроек и ошибок валидации
    database_url: SecretStr
    db_pool_size: int = 5
    db_max_overflow: int = 5

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, ValueError, TypeError):
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        return value

    @field_validator("db_pool_size", "db_max_overflow")
    @classmethod
    def positive_pool_size(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Pool sizes must be positive")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
