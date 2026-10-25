"""извлекает признаки новости по общей схеме сервиса хранения"""

from app.schemas.news import NewsFeatures, NewsForTagging
from app.schemas.tagging import NewsTaggingOutput
from app.services.tag_catalog import load_catalog

from ._common import (
    model_object,
    normalize_city_codes,
    settings,
    validate_configuration,
    validate_features,
)
from .bad_news import load_bad_news


class NewsTagger:
    """возвращает NewsFeatures, не открывает БД и не меняет исходную новость"""

    version = "news-features-v4:business-context-v1"

    def __init__(self, *, catalog_path=None, bad_news_path=None, transport=None):
        """сохраняет справочник и транспорт для обращения к модели"""
        self.catalog = load_catalog(catalog_path)
        self.bad_news_path = bad_news_path
        self.transport = transport

    def check_configuration(self) -> None:
        """проверяет настройки до получения порции новостей, тестовый транспорт не требует ключа"""
        if self.transport is None:
            validate_configuration(settings(), "LLM_MODEL_TAGGING")

    def tag(self, news: NewsForTagging) -> NewsFeatures:
        """размечает текст, а ID результата берёт из входной новости, не из ответа LLM"""
        if not isinstance(news, NewsForTagging):
            raise TypeError("Expected NewsForTagging")
        if not news.title.strip() and not news.text.strip():
            raise ValueError("News title or text is required")
        examples = load_bad_news(path=self.bad_news_path)
        examples = [
            {**row, "title": row["title"][:500], "text": row["text"][:3000]}
            for row in examples
        ]
        output = model_object(
            "LLM_MODEL_TAGGING",
            "Выдели темы, тип события, экономические факторы, отрасли и краткое изложение фактов. "
            "business_scope: general для общих правил и рыночных условий, industry для "
            "изменений условий отрасли, local для местной инфраструктуры и мер, organization "
            "для события отдельной организации без подтверждённых последствий для отрасли, "
            "unknown при нехватке данных. business_relevance оценивает деловую значимость: "
            "0.9–1 обязательные правила и крупные изменения условий, 0.7–0.85 конкретные "
            "возможности и риски, 0.4–0.65 отраслевые кейсы и проекты, 0.1–0.35 бытовые "
            "события и слабые сигналы, 0 без деловой связи. Не завышай оценку планов, "
            "церемоний и школьных мероприятий, не придумывай последствия. "
            "industries содержит коды из business, только когда обозначена отрасль события. "
            "Неизвестные признаки оставляй пустыми. Для общенационального события укажи "
            "nationwide=true, не перечисляй все регионы. incorrect_examples содержит "
            "ошибочные назначения tags, а не правильные ответы. Они не запрещают эти теги "
            "для других новостей. Текст может быть сокращён, не восполняй пропущенные факты. "
            "Сохраняй статус и модальность событий: предложение, план и возможность не означают "
            "завершённую работу или принятое обязательство. Доступное подключение к сетям "
            "не означает, что сети подключены; предполагаемый оператор не означает назначенного.",
            {
                "news": {
                    "title": news.title[:1000],
                    "text": news.text[:30000],
                    "published_at": news.published_at.isoformat(),
                    "text_truncated": len(news.text) > 30000,
                },
                "incorrect_examples": examples,
            },
            self.catalog,
            NewsTaggingOutput,
            self.transport,
        )
        normalize_city_codes(output, self.catalog)
        validate_features(output, self.catalog)
        if set(output.industries) - set(self.catalog["business"].values()):
            raise ValueError("Unknown industry code")
        return NewsFeatures(news_id=news.news_id, **output.model_dump())
