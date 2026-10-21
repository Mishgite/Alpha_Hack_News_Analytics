from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import (
    Base,
    CreatedAt,
    UUIDPrimaryKey,
    json_array,
    json_object,
    timestamp,
)


class Company(Base):
    """профиль компании из исходных данных; неизвестные характеристики остаются пустыми"""

    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(primary_key=True)
    okved_code: Mapped[str | None]
    okved_name: Mapped[str | None]
    industry: Mapped[str | None] = mapped_column(index=True)
    industry_code: Mapped[str | None]
    country_code: Mapped[str | None]
    registered_region_code: Mapped[str | None]
    operating_region_codes: Mapped[list | None]
    known_factor_interests: Mapped[list] = json_array()
    city: Mapped[str | None]
    region: Mapped[str | None]
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    group_id: Mapped[str | None] = mapped_column(index=True)
    profile_json: Mapped[dict] = json_object()
    profile_version: Mapped[str]
    updated_at: Mapped[datetime] = timestamp(
        server_default=func.now(), onupdate=func.now()
    )


class CompanyFeature(UUIDPrimaryKey, Base):
    """значение признака вместе с файлом и полем, из которых оно получено"""

    __tablename__ = "company_features"
    __table_args__ = (UniqueConstraint("company_id", "feature_key", "calc_method"),)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    feature_key: Mapped[str]
    value_json: Mapped[dict] = json_object()
    origin_file: Mapped[str]
    origin_field: Mapped[str | None]
    calc_method: Mapped[str]
    confidence_type: Mapped[str | None]
    observed_at: Mapped[datetime] = timestamp(server_default=func.now())


class CompanyLink(UUIDPrimaryKey, Base):
    """подтверждённая связь двух компаний: платёж, общая группа или связанное лицо"""

    __tablename__ = "company_links"
    __table_args__ = (
        UniqueConstraint(
            "from_company_id", "to_company_id", "link_type", "source_dataset"
        ),
        CheckConstraint(
            "link_type IN ('payment','same_group','shared_person')", name="link_type"
        ),
    )
    from_company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    to_company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    link_type: Mapped[str]
    pay_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    pay_count: Mapped[int | None]
    source_dataset: Mapped[str]


class CompanyContextSnapshot(UUIDPrimaryKey, CreatedAt, Base):
    """копия контекста компании, на которую ссылаются конкретная лента и разбор"""

    __tablename__ = "company_context_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "context_hash"),
        UniqueConstraint("id", "company_id", name="uq_company_context_id_company"),
    )
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    context_hash: Mapped[str]
    payload_json: Mapped[dict] = json_object()
    source_versions_json: Mapped[dict] = json_object()


class User(UUIDPrimaryKey, CreatedAt, Base):
    """выбранная компания, должность для персонализации и отдельная роль доступа"""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "job_role IN ('ceo','cfo','treasury','accountant','employee','other')",
            name="job_role",
        ),
    )
    city: Mapped[str]
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    job_role: Mapped[str] = mapped_column(server_default="other")
    access_role: Mapped[str] = mapped_column(server_default="user")


class UserSession(UUIDPrimaryKey, Base):
    """хэш токена сессии и её срок действия; сам токен не сохраняется"""

    __tablename__ = "user_sessions"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = timestamp()
    revoked_at: Mapped[datetime | None] = timestamp()


class Tag(Base):
    """общий справочник тем, с которым сверяется разметка новостей и интересы"""

    __tablename__ = "tags"
    id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    description: Mapped[str | None]
    category: Mapped[str | None]
    active: Mapped[bool] = mapped_column(server_default="true")


class TagAlias(Base):
    """другое написание темы, которое нужно привести к одному id из справочника"""

    __tablename__ = "tag_aliases"
    alias: Mapped[str] = mapped_column(primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"))


class CompanyTag(Base):
    """корпоративный интерес с весом и происхождением: правило или ручная настройка"""

    __tablename__ = "company_tags"
    __table_args__ = (
        CheckConstraint("base_weight BETWEEN 0 AND 2", name="weight_range"),
        CheckConstraint("origin IN ('rule','manual')", name="origin"),
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    origin: Mapped[str] = mapped_column(primary_key=True)
    reason: Mapped[str | None]
    rule_version: Mapped[str | None]
    base_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), server_default="1")


class UserTag(CreatedAt, Base):
    """тема, которую пользователь добавил сам; сохраняется при смене компании"""

    __tablename__ = "user_tags"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class UserTagOverride(Base):
    """явное отключение темы пользователем без удаления самой темы из справочника"""

    __tablename__ = "user_tag_overrides"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    disabled: Mapped[bool] = mapped_column(server_default="false")
    updated_at: Mapped[datetime] = timestamp(
        server_default=func.now(), onupdate=func.now()
    )


class UserTagPreference(Base):
    """место для сохранённого пересчёта предпочтений; текущий репозиторий читает реакции напрямую"""

    __tablename__ = "user_tag_preferences"
    __table_args__ = (
        CheckConstraint(
            "likes_cnt >= 0 AND dislikes_cnt >= 0", name="nonnegative_counts"
        ),
        CheckConstraint("preference_weight BETWEEN 0 AND 2", name="weight_range"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    likes_cnt: Mapped[int] = mapped_column(server_default="0")
    dislikes_cnt: Mapped[int] = mapped_column(server_default="0")
    preference_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), server_default="1"
    )
    recalculated_at: Mapped[datetime] = timestamp(server_default=func.now())
