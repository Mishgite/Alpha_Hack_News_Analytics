import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from math import log1p
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import CompanyData, CompanyTagInput, ProfileInputs, UserData
from app.schemas.ranking import RankingProfile
from app.schemas.services import (
    Interests,
    ProfilePolicy,
    Registration,
    SessionGrant,
    UserSettings,
)

from ._common import digest, required
from .company_topics import initial_company_topics, operating_topics
from .geography import company_geography


@lru_cache
def demo_company_ids() -> tuple[str, ...]:
    """читает выбранные для демонстрации ID компаний разных отраслей, регионов и размеров"""
    path = Path(__file__).resolve().parents[1] / "demo_companies.json"
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def build_profile(inputs: ProfileInputs, policy: ProfilePolicy) -> RankingProfile:
    """рассчитывает веса тем для ранжировщика

    для каждой темы берёт наибольший вес из настроек компании, должности и пользователя
    лайки увеличивают вес, дизлайки уменьшают, итог ограничен от 0 до 2
    отключённым темам ставит 0
    """
    weights = dict(policy.role_weights.get(inputs.user.job_role, {}))
    for tag_id, weight in operating_topics(inputs.company).items():
        weights[tag_id] = max(weights.get(tag_id, 0), weight)
    for tag in inputs.company_tags:
        weights[tag.tag_id] = max(weights.get(tag.tag_id, 0), tag.base_weight)
    for tag_id in inputs.personal_tag_ids:
        weights[tag_id] = max(weights.get(tag_id, 0), 1.0)
    for tag_id, base in weights.items():
        counts = inputs.reaction_counts.get(tag_id)
        correction = (
            1.0
            if counts is None
            else max(
                0,
                min(
                    2,
                    1
                    + policy.reaction_alpha
                    * (log1p(counts.likes) - log1p(counts.dislikes)),
                ),
            )
        )
        weights[tag_id] = max(0, min(2, base * correction))
    for tag_id in inputs.disabled_tag_ids:
        weights[tag_id] = 0.0
    company = inputs.company
    country, registered, operating = company_geography(company)
    return RankingProfile(
        user_id=inputs.user.id,
        company_id=company.id,
        job_role=inputs.user.job_role,
        tag_weights=weights,
        company_tag_ids=sorted(
            (
                {tag.tag_id for tag in initial_company_topics(company)}
                or {tag.tag_id for tag in inputs.company_tags}
            )
            | {tag.tag_id for tag in inputs.company_tags if tag.origin == "manual"}
        ),
        personal_tag_ids=sorted(inputs.personal_tag_ids),
        industry_code=company.industry_code,
        country_code=country,
        registered_region_code=registered,
        operating_region_codes=operating,
        known_factor_interests=company.known_factor_interests,
        profile_version=digest(
            {
                "profile_builder": "company-topics-v2-manual",
                "inputs": inputs.model_dump(mode="json"),
                "policy": policy.model_dump(mode="json"),
            }
        ),
    )


class ProfileService:
    """паттерн Service Layer: создаёт пользователей и сессии, сохраняет компании и настройки интересов"""

    def __init__(
        self,
        *,
        policy: ProfilePolicy | None = None,
        uow_factory=UnitOfWork,
    ):
        """сохраняет настройки расчёта весов и фабрику UnitOfWork

        внедрение зависимостей (Dependency Injection): uow_factory задаёт способ создания UnitOfWork
        """
        self.policy = (policy or ProfilePolicy()).model_copy(deep=True)
        self._uow = uow_factory

    def list_companies(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        query: str = "",
        demo_selection: bool = False,
    ) -> list[CompanyData]:
        """возвращает страницу компаний для выбора, отсортированную по ID"""
        with self._uow() as db:
            company_ids = demo_company_ids() if demo_selection else None
            if demo_selection and not db.companies.list(limit=1, company_ids=company_ids):
                company_ids = ("demo-api-company",)
            return db.companies.list(
                limit=limit,
                offset=offset,
                query=query,
                company_ids=company_ids,
            )

    def save_company(self, company: CompanyData) -> CompanyData:
        """создаёт компанию или заменяет её профиль целиком данными импорта"""
        required(company.id, "company_id")
        required(company.profile_version, "profile_version")
        with self._uow() as db:
            result = db.companies.save(company)
            db.commit()
            return result

    def create_companies(self, companies: list[CompanyData]) -> list[str]:
        """добавляет до 500 компаний одной транзакцией, возвращает ID только новых записей"""
        if len(companies) > 500:
            raise ValueError("A batch cannot contain more than 500 companies")
        if not companies:
            return []
        for company in companies:
            required(company.id, "company_id")
            required(company.profile_version, "profile_version")
        ids = [company.id for company in companies]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate company IDs in batch")
        with self._uow() as db:
            result = db.companies.create_many(companies)
            for company in companies:
                if company.id in result:
                    self._seed_company_topics(db, company)
            db.commit()
            return result

    def get_company(self, company_id: str) -> CompanyData:
        """возвращает компанию для разметки или вызывает LookupError"""
        with self._uow() as db:
            company = db.companies.get(company_id)
            if company is None:
                raise LookupError("Company not found")
            return company

    def save_company_tagging(
        self, expected: CompanyData, tags: list[CompanyTagInput]
    ) -> None:
        """заменяет автоматические темы без удаления ручных, проверяет версию данных компании"""
        with self._uow() as db:
            db.companies.save_company_tagging(expected, tags)
            db.commit()

    def set_company_tags(self, company_id: str, tags: list[CompanyTagInput]) -> None:
        """заменяет темы компании и их веса, сохраняя личные настройки пользователей"""
        with self._uow() as db:
            db.companies.set_tags(required(company_id, "company_id"), tags)
            db.commit()

    def _seed_company_topics(self, db, company):
        """сохраняет начальные отраслевые темы, если разметки компании ещё нет"""
        tags = initial_company_topics(company)
        if not tags:
            return False
        active = {tag.id for tag in db.news.list_tags()}
        return db.companies.seed_tags_if_empty(
            company, [tag for tag in tags if tag.tag_id in active]
        )

    def ensure_company_topics(self, company_id: str) -> bool:
        """заполняет пустые темы существующей компании по ОКВЭД без вызова модели"""
        with self._uow() as db:
            company = db.companies.get(company_id)
            if company is None:
                raise LookupError("Company not found")
            changed = self._seed_company_topics(db, company)
            db.commit()
            return changed

    def register_demo(
        self, data: Registration, *, session_hours: int = 24
    ) -> SessionGrant:
        """создаёт пользователя и сессию для существующей компании

        возвращает пользователя, токен и срок действия сессии
        при ошибке отменяет обе записи
        """
        if not 1 <= session_hours <= 720:
            raise ValueError("session_hours must be in [1, 720]")
        token = token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(hours=session_hours)
        with self._uow() as db:
            company = db.companies.get(data.company_id)
            if company is None:
                raise LookupError("Company not found")
            self._seed_company_topics(db, company)
            user = db.users.create(**data.model_dump())
            db.users.create_session(user.id, token, expires)
            db.commit()
        return SessionGrant(user=user, token=token, expires_at=expires)

    def authenticate(self, token: str) -> UserData:
        """находит пользователя по токену, для недействующей сессии вызывает PermissionError"""
        with self._uow() as db:
            user = db.users.resolve_session(token)
            if user is None:
                raise PermissionError("Invalid or expired session")
            return user

    def logout(self, token: str) -> None:
        """закрывает сессию по токену, повторный вызов ничего не меняет"""
        with self._uow() as db:
            db.users.revoke_session(token)
            db.commit()

    def get_profile(self, user_id: UUID) -> ProfileInputs:
        """возвращает данные пользователя, компании, выбранные темы и количество реакций по темам"""
        with self._uow() as db:
            return db.users.get_profile_inputs(user_id)

    def switch_company(self, user_id: UUID, company_id: str) -> ProfileInputs:
        """меняет компанию и возвращает профиль с её данными и прежними личными темами"""
        with self._uow() as db:
            db.users.switch_company(user_id, required(company_id, "company_id"))
            self._seed_company_topics(db, db.companies.get(company_id))
            result = db.users.get_profile_inputs(user_id)
            db.commit()
            return result

    def update_settings(self, user_id: UUID, settings: UserSettings) -> UserData:
        """сохраняет город и должность пользователя, не меняя его права доступа"""
        with self._uow() as db:
            result = db.users.update_settings(
                user_id, **settings.model_dump(exclude_unset=True)
            )
            db.commit()
            return result

    def set_interests(self, user_id: UUID, settings: Interests) -> ProfileInputs:
        """заменяет личные и отключённые темы, затем возвращает обновлённый профиль

        проверяет, что темы существуют, активны и не входят в оба списка сразу
        """
        if set(settings.personal) & set(settings.disabled):
            raise ValueError("A tag cannot be both personal and disabled")
        with self._uow() as db:
            db.users.set_interests(user_id, **settings.model_dump())
            result = db.users.get_profile_inputs(user_id)
            db.commit()
            return result

    def get_ranking_profile(self, user_id: UUID) -> RankingProfile:
        """возвращает профиль с весами тем, рассчитанными по текущим настройкам и реакциям"""
        return build_profile(self.get_profile(user_id), self.policy)

    def pending_tagging(self, version, limit=2):
        """возвращает ограниченную порцию профилей для фонового разметчика"""
        with self._uow() as db:
            return db.companies.pending_tagging(version, limit)

    def get_context(self, user_id):
        """возвращает снимок признаков выбранной компании для интерфейса доказательств"""
        with self._uow() as db:
            profile = db.users.get_profile_inputs(user_id)
            from ._common import company_context

            result = company_context(db, profile.company)
            db.commit()
            return result
