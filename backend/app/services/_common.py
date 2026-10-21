import hashlib
import json

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import CompanyData, ContextData


def digest(value: object) -> str:
    """сортирует ключи JSON и вычисляет SHA-256, чтобы порядок ключей не влиял на хэш"""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def company_context(db: UnitOfWork, company: CompanyData) -> ContextData:
    """сохраняет снимок компании с признаками, их источниками, связями и темами

    возвращает ContextData, транзакцию завершает вызывающий сервис
    """
    return db.companies.save_context(
        company.id,
        {
            **company.model_dump(mode="json"),
            **db.companies.get_context_evidence(company.id),
        },
        {"profile": company.profile_version},
    )


def required(value: str, name: str) -> str:
    """убирает пробелы по краям строки и вызывает ValueError, если строка пустая"""
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must be non-empty")
    return value
