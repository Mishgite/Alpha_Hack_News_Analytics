from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    Company,
    CompanyContextSnapshot,
    CompanyFeature,
    CompanyLink,
    CompanyTag,
    NewsTag,
    Tag,
    User,
    UserReaction,
    UserSession,
    UserTag,
    UserTagOverride,
)
from app.schemas.database import (
    CompanyData,
    CompanyTagInput,
    ContextData,
    ProfileInputs,
    SessionData,
    TagReactionCounts,
    UserData,
)
from app.schemas.ranking import JobRole, RankingProfile, Weight


def _require_user(session: Session, user_id: UUID, *, lock: bool = False) -> User:
    """находит пользователя или вызывает LookupError; lock блокирует строку до конца транзакции"""
    query = (
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    # блокировка нужна операциям, которым нельзя менять компанию пользователя посередине записи
    if lock:
        query = query.with_for_update()
    user = session.scalar(query)
    if user is None:
        raise LookupError("User not found")
    return user


def _require_company_access(session: Session, user_id: UUID, company_id: str) -> User:
    """блокирует пользователя и проверяет совпадение выбранной компании с company_id"""
    user = _require_user(session, user_id, lock=True)
    # сейчас доступ определяется выбранной компанией демопользователя, а не его должностью
    if user.company_id != company_id:
        raise PermissionError("Company is not selected for this demo user")
    return user


class CompanyRepository:
    """паттерн Repository: читает и записывает компании и снимки их данных в общей сессии"""

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def get(self, company_id: str) -> CompanyData | None:
        """возвращает компанию по строковому ID или None, если записи нет"""
        row = self._session.get(Company, company_id)
        return CompanyData.model_validate(row) if row else None

    def list(self, *, limit: int = 50, offset: int = 0) -> list[CompanyData]:
        """возвращает компании по ID с ограничением размера страницы и смещением"""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid company pagination")
        rows = self._session.scalars(
            select(Company).order_by(Company.id).offset(offset).limit(limit)
        )
        return [CompanyData.model_validate(row) for row in rows]

    def save(self, company: CompanyData) -> CompanyData:
        """создаёт компанию или заменяет все поля существующей записи по ID, возвращает CompanyData"""
        values = company.model_dump()
        stmt = insert(Company).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Company.id],
            set_={
                **{k: v for k, v in values.items() if k != "id"},
                "updated_at": func.now(),
            },
        ).returning(Company)
        row = self._session.scalars(
            stmt.execution_options(populate_existing=True)
        ).one()
        return CompanyData.model_validate(row)

    def set_tags(self, company_id: str, tags: list[CompanyTagInput]) -> None:
        """заменяет темы компании после проверки тегов и их происхождения

        блокирует компанию до конца транзакции, чтобы профиль не собирался во время замены
        """
        company = self._session.scalar(
            select(Company)
            .where(Company.id == company_id)
            .with_for_update(key_share=True)
        )
        if company is None:
            raise LookupError("Company not found")
        keys = [(tag.tag_id, tag.origin) for tag in tags]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate company tags")
        ids = {tag.tag_id for tag in tags}
        active = set(
            self._session.scalars(select(Tag.id).where(Tag.id.in_(ids), Tag.active))
        )
        if ids != active:
            raise ValueError("Unknown or inactive tag")
        self._session.execute(
            delete(CompanyTag).where(CompanyTag.company_id == company_id)
        )
        self._session.add_all(
            [CompanyTag(company_id=company_id, **tag.model_dump()) for tag in tags]
        )
        self._session.flush()

    def get_context_evidence(self, company_id: str) -> dict:
        """возвращает источники признаков, связи и темы компании для AI

        перед вызовом нужно заблокировать компанию до конца транзакции
        """
        features = self._session.scalars(
            select(CompanyFeature)
            .where(CompanyFeature.company_id == company_id)
            .order_by(CompanyFeature.id)
        ).all()
        relations = self._session.scalars(
            select(CompanyLink)
            .where(
                (CompanyLink.from_company_id == company_id)
                | (CompanyLink.to_company_id == company_id),
            )
            .order_by(CompanyLink.id)
        ).all()
        tags = self._session.scalars(
            select(CompanyTag)
            .join(Tag)
            .where(
                CompanyTag.company_id == company_id,
                Tag.active,
            )
            .order_by(CompanyTag.tag_id, CompanyTag.origin)
        ).all()
        return {
            "features": [
                {
                    "id": str(row.id),
                    "key": row.feature_key,
                    "value": row.value_json,
                    "origin_file": row.origin_file,
                    "origin_field": row.origin_field,
                    "calc_method": row.calc_method,
                    "confidence_type": row.confidence_type,
                    "observed_at": row.observed_at.isoformat(),
                }
                for row in features
            ],
            "relations": [
                {
                    "id": str(row.id),
                    "from_company_id": row.from_company_id,
                    "to_company_id": row.to_company_id,
                    "link_type": row.link_type,
                    "pay_amount": str(row.pay_amount)
                    if row.pay_amount is not None
                    else None,
                    "pay_count": row.pay_count,
                    "source_dataset": row.source_dataset,
                }
                for row in relations
            ],
            "tags": [
                {
                    "id": row.tag_id,
                    "origin": row.origin,
                    "base_weight": float(row.base_weight),
                    "reason": row.reason,
                    "rule_version": row.rule_version,
                }
                for row in tags
            ],
        }

    def save_context(
        self, company_id: str, payload: dict, versions: dict
    ) -> ContextData:
        # одинаковый контекст и версии источников должны давать один хэш независимо от порядка ключей
        """сохраняет контекст и версии источников; одинаковые данные компании дают один снимок"""
        canonical = json.dumps(
            {"payload": payload, "versions": versions},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        self._session.execute(
            insert(CompanyContextSnapshot)
            .values(
                company_id=company_id,
                context_hash=digest,
                payload_json=payload,
                source_versions_json=versions,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "context_hash"])
        )
        row = self._session.scalars(
            select(CompanyContextSnapshot).where(
                CompanyContextSnapshot.company_id == company_id,
                CompanyContextSnapshot.context_hash == digest,
            )
        ).one()
        return ContextData.model_validate(row)


class UserRepository:
    """паттерн Repository: читает и записывает пользователей, сессии и настройки интересов"""

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def get(self, user_id: UUID) -> UserData:
        """возвращает пользователя по UUID; при отсутствии вызывает LookupError"""
        return UserData.model_validate(_require_user(self._session, user_id))

    def update_settings(
        self, user_id: UUID, *, city: str, job_role: JobRole
    ) -> UserData:
        """блокирует пользователя, меняет город и должность, возвращает обновлённые данные"""
        user = _require_user(self._session, user_id, lock=True)
        user.city, user.job_role = city, job_role
        self._session.flush()
        return UserData.model_validate(user)

    def revoke_session(self, raw_token: str) -> None:
        """помечает сессию отозванной по хэшу токена; неизвестный токен не вызывает ошибку"""
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        self._session.execute(
            update(UserSession)
            .where(
                UserSession.token_hash == digest,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )

    def create(
        self, *, company_id: str, city: str, job_role: JobRole = "other"
    ) -> UserData:
        """создаёт пользователя с access_role=user и возвращает его с назначенным UUID"""
        row = User(
            company_id=company_id, city=city, job_role=job_role, access_role="user"
        )
        self._session.add(row)
        self._session.flush()
        return UserData.model_validate(row)

    def switch_company(self, user_id: UUID, company_id: str) -> UserData:
        """проверяет существование компании и меняет выбор пользователя под блокировкой"""
        user = _require_user(self._session, user_id, lock=True)
        if self._session.get(Company, company_id) is None:
            raise LookupError("Company not found")
        user.company_id = company_id
        self._session.flush()
        return UserData.model_validate(user)

    def set_interests(
        self, user_id: UUID, *, personal: list[str], disabled: list[str]
    ) -> None:
        """проверяет активность тегов и полностью заменяет личные и отключённые темы пользователя"""
        _require_user(self._session, user_id, lock=True)
        ids = set(personal) | set(disabled)
        valid = set(
            self._session.scalars(select(Tag.id).where(Tag.id.in_(ids), Tag.active))
        )
        if valid != ids:
            raise ValueError("Unknown or inactive tag")
        # это полная замена личных настроек; теги компании и исходные теги новостей остаются на месте
        self._session.execute(delete(UserTag).where(UserTag.user_id == user_id))
        self._session.execute(
            delete(UserTagOverride).where(UserTagOverride.user_id == user_id)
        )
        self._session.add_all(
            [UserTag(user_id=user_id, tag_id=t) for t in set(personal)]
        )
        self._session.add_all(
            [
                UserTagOverride(user_id=user_id, tag_id=t, disabled=True)
                for t in set(disabled)
            ]
        )
        self._session.flush()

    def get_profile_inputs(self, user_id: UUID) -> ProfileInputs:
        """собирает данные пользователя, компании, темы и количество реакций по ним

        блокирует пользователя и компанию до конца транзакции
        веса тем рассчитывает сервис
        """
        user = _require_user(self._session, user_id, lock=True)
        company = self._session.scalar(
            select(Company)
            .where(
                Company.id == user.company_id,
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        # считаем действующие реакции: повторные отправки одного лайка не должны увеличивать вес темы
        counts = self._session.execute(
            select(
                NewsTag.tag_id,
                func.count().filter(UserReaction.reaction == "like"),
                func.count().filter(UserReaction.reaction == "dislike"),
            )
            .join(UserReaction, UserReaction.news_id == NewsTag.news_id)
            .join(Tag, Tag.id == NewsTag.tag_id)
            .where(UserReaction.user_id == user_id, Tag.active)
            .group_by(NewsTag.tag_id)
        ).all()
        corporate = self._session.scalars(
            select(CompanyTag)
            .join(Tag, Tag.id == CompanyTag.tag_id)
            .where(CompanyTag.company_id == user.company_id, Tag.active)
            .order_by(CompanyTag.tag_id, CompanyTag.origin)
        ).all()
        return ProfileInputs(
            user=UserData.model_validate(user),
            company=CompanyData.model_validate(company),
            company_tags=[CompanyTagInput.model_validate(row) for row in corporate],
            personal_tag_ids=list(
                self._session.scalars(
                    select(UserTag.tag_id)
                    .join(Tag, Tag.id == UserTag.tag_id)
                    .where(UserTag.user_id == user_id, Tag.active)
                    .order_by(UserTag.tag_id)
                )
            ),
            disabled_tag_ids=list(
                self._session.scalars(
                    select(UserTagOverride.tag_id)
                    .join(Tag, Tag.id == UserTagOverride.tag_id)
                    .where(
                        UserTagOverride.user_id == user_id,
                        UserTagOverride.disabled,
                        Tag.active,
                    )
                    .order_by(UserTagOverride.tag_id)
                )
            ),
            reaction_counts={
                tag: TagReactionCounts(likes=likes, dislikes=dislikes)
                for tag, likes, dislikes in counts
            },
        )

    def get_ranking_profile(
        self,
        user_id: UUID,
        *,
        tag_weights: dict[str, Weight],
        profile_version: str,
    ) -> RankingProfile:
        """собирает RankingProfile из данных пользователя и переданных готовых весов и версии"""
        inputs = self.get_profile_inputs(user_id)
        company = inputs.company
        return RankingProfile(
            user_id=user_id,
            company_id=company.id,
            job_role=inputs.user.job_role,
            tag_weights=tag_weights,
            profile_version=profile_version,
            industry_code=company.industry_code,
            country_code=company.country_code,
            registered_region_code=company.registered_region_code,
            operating_region_codes=company.operating_region_codes,
            known_factor_interests=company.known_factor_interests,
        )

    def create_session(
        self, user_id: UUID, raw_token: str, expires_at: datetime
    ) -> SessionData:
        """сохраняет хэш токена и срок сессии, возвращает SessionData без исходного токена"""
        if len(raw_token) < 32 or expires_at.tzinfo is None:
            raise ValueError("Use a long token and timezone-aware expiry")
        # в БД остаётся только хэш токена; исходный токен не попадает в возвращаемый DTO
        row = UserSession(
            user_id=user_id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=expires_at,
        )
        self._session.add(row)
        self._session.flush()
        return SessionData.model_validate(row)

    def resolve_session(self, raw_token: str) -> UserData | None:
        """возвращает пользователя по неистёкшей, неотозванной сессии либо None"""
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        row = self._session.scalar(
            select(User)
            .join(UserSession)
            .where(
                UserSession.token_hash == digest,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > func.now(),
            )
        )
        return UserData.model_validate(row) if row else None
