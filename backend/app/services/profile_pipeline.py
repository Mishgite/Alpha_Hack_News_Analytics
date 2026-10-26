"""передаёт подтверждённые сведения компании разметчику и сохраняет тематические интересы"""

import json
from uuid import UUID

from pydantic import TypeAdapter

from app.schemas.database import CompanyTagInput
from app.schemas.ranking import Weight
from app.schemas.tagging import ProfileForTagging, ProfileTags

from .company_topics import initial_company_topics
from .profiles import ProfileService

TAGGING_VERSION = "profile-tags-v3:"


class ProfilePipeline:
    """размечает компании и предлагает интересы пользователю без автоматической смены его настроек"""

    def __init__(self, *, profile_service=None, tagger=None):
        """внедрение зависимостей: принимает сервис профилей и внешний разметчик"""
        self.profiles = (
            profile_service if profile_service is not None else ProfileService()
        )
        if tagger is None:
            from .ai_agents import ProfileTagger

            tagger = ProfileTagger()
        self.tagger = tagger

    @staticmethod
    def _description(company, *, job_role=None) -> str:
        """передаёт известные признаки без произвольного содержимого profile_json"""
        fields = {
            "okved_code",
            "okved_name",
            "industry",
            "city",
            "region",
            "industry_code",
            "country_code",
            "registered_region_code",
            "operating_region_codes",
            "known_factor_interests",
        }
        data = company.model_dump(mode="json", include=fields, exclude_none=True)
        from .ai_agents.analysis import CONTEXT_FIELDS, PRODUCT_FIELDS

        data.update(
            {
                key: company.profile_json[key]
                for key in PRODUCT_FIELDS
                if key not in CONTEXT_FIELDS
                and company.profile_json.get(key) is not None
            }
        )
        if job_role is not None:
            data["job_role"] = job_role
        return json.dumps(data, ensure_ascii=False)

    def prepare_company(self, company_id: str, version: str) -> bool:
        """размечает ещё не готовую версию профиля и сохраняет результат для импорта и воркера"""
        from app.infrastructure.database.worker_lock import company_tagging_lock

        from .runtime import RuntimeService

        runtime = RuntimeService(uow_factory=self.profiles._uow)
        with company_tagging_lock(company_id):
            company = self.profiles.get_company(company_id)
            state_version = company.profile_version + "|" + version
            state = runtime.get("profile:" + company_id)
            if (
                state
                and state["value"].get("version") == state_version
                and state["value"].get("status") == "ready"
            ):
                return False
            try:
                self.tag_company(company_id, state_version=state_version)
            except Exception as error:
                runtime.save(
                    "profile:" + company_id,
                    {
                        "version": state_version,
                        "status": "failed",
                        "error": type(error).__name__,
                    },
                )
                raise
            return True

    def tag_company(
        self,
        company_id: str,
        *,
        base_weight: float = 1.0,
        state_version: str | None = None,
    ) -> ProfileTags:
        """сохраняет предложенные темы с заданным весом, не меняет фактическую географию компании"""
        weight = TypeAdapter(Weight).validate_python(base_weight)
        company = self.profiles.get_company(company_id)
        if state_version is not None and not state_version.startswith(
            company.profile_version + "|"
        ):
            raise ValueError("Company changed before tagging")
        result = self.tagger.tag(
            ProfileForTagging(
                city=company.city or "",
                text=self._description(company),
            )
        )
        topics = {
            tag.id: CompanyTagInput(tag_id=tag.id, origin="rule", base_weight=weight)
            for tag in result.tags
        }
        for tag in initial_company_topics(company):
            if (
                tag.tag_id not in topics
                or topics[tag.tag_id].base_weight < tag.base_weight
            ):
                topics[tag.tag_id] = tag
        state = (
            {
                "version": state_version,
                "status": "ready",
                "features": result.model_dump(mode="json"),
            }
            if state_version
            else None
        )
        self.profiles.save_company_tagging(company, list(topics.values()), state=state)
        return result

    def suggest_interests(self, user_id: UUID) -> ProfileTags:
        """возвращает предложения с учётом должности, применение остаётся выбором пользователя"""
        profile = self.profiles.get_profile(user_id)
        return self.tagger.tag(
            ProfileForTagging(
                city=profile.user.city,
                text=self._description(profile.company, job_role=profile.user.job_role),
            )
        )
