"""общие типы колонок и правила именования ограничений для всех таблиц"""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # имена ограничений получаются одинаковыми в моделях и в SQL-схеме
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    # словари и списки сохраняются как JSONB, чтобы по их содержимому можно было искать
    type_annotation_map: ClassVar[dict] = {str: Text, dict: JSONB, list: JSONB}


class UUIDPrimaryKey:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


def timestamp(**kwargs):
    return mapped_column(DateTime(timezone=True), **kwargs)


class CreatedAt:
    created_at: Mapped[datetime] = timestamp(server_default=func.now())


def json_object():
    # default создаёт новый словарь для каждой записи; server_default работает и при вставке через SQL
    return mapped_column(JSONB, default=dict, server_default="{}")


def json_array():
    return mapped_column(JSONB, default=list, server_default="[]")
