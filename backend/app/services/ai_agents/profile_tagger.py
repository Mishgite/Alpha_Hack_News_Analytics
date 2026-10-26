"""предлагает темы по подтверждённым данным компании или сотрудника"""

from app.schemas.tagging import ProfileForTagging, ProfileTags
from app.services.tag_catalog import load_catalog

from ._common import model_features


class ProfileTagger:
    """возвращает темы профиля без изменения прав доступа и личных предпочтений"""

    def __init__(self, *, catalog_path=None, transport=None):
        """сохраняет справочник и транспорт модели"""
        self.catalog = load_catalog(catalog_path)
        self.transport = transport

    def tag(self, profile: ProfileForTagging) -> ProfileTags:
        """выделяет интересы из деятельности и должности, не угадывает отсутствующие факты"""
        if not isinstance(profile, ProfileForTagging):
            raise TypeError("Expected ProfileForTagging")
        return model_features(
            "LLM_MODEL_CONTEXT",
            "Выдели темы по описанию деятельности и должности. Не выводи отрасль из названия "
            "компании. city обозначает местонахождение, не весь регион деятельности. "
            "Не присваивай всем должностям одинаковые темы управления и налогов. "
            "При недостатке данных верни пустые темы и неизвестную географию.",
            {"profile": profile.model_dump()},
            self.catalog,
            ProfileTags,
            self.transport,
        )
