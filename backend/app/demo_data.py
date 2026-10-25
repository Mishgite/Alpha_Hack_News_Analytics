"""добавляет отдельные синтетические записи для проверки API без парсера и LLM"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

if __name__ == "__main__" and not __package__:
    # при запуске файла напрямую пакет app ищется от папки backend
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.database import CompanyData, CompanyTagInput
from app.schemas.news import Geography, NewsFeatures, NewsTag
from app.schemas.services import IncomingNews
from app.services import NewsService, ProfileService

COMPANY_ID = "demo-api-company"
TAG_ID = "demo-api-logistics"
SOURCE = "demo-api-source"


def create_demo_data(
    profiles: ProfileService | None = None, news: NewsService | None = None
) -> list[str]:
    """сохраняет демокомпанию и три новости, повторный запуск обновляет те же записи"""
    profiles = profiles if profiles is not None else ProfileService()
    news = news if news is not None else NewsService()
    news.register_tag(TAG_ID, display_name="Демо: логистика")
    news.register_source(SOURCE, kind="demo")
    profiles.save_company(
        CompanyData(
            id=COMPANY_ID,
            profile_version="demo-v1",
            industry="Синтетическая транспортная компания",
            city="Москва",
            profile_json={"synthetic": True, "purpose": "Проверка API"},
        )
    )
    profiles.set_company_tags(
        COMPANY_ID, [CompanyTagInput(tag_id=TAG_ID, origin="manual", base_weight=1)]
    )
    examples = [
        (
            "ДЕМО: изменение стоимости перевозок",
            "Синтетический пример новости о тарифах на перевозки",
            True,
        ),
        (
            "ДЕМО: открытие складского комплекса",
            "Синтетический пример новости о складской инфраструктуре",
            True,
        ),
        (
            "ДЕМО: обновление офисного оборудования",
            "Синтетический пример новости без совпадения с темами компании",
            False,
        ),
    ]
    now = datetime.now(UTC)
    ids = []
    for index, (title, body, relevant) in enumerate(examples):
        article = news.save_news(
            IncomingNews(
                source=SOURCE,
                external_id=f"demo-{index}",
                title=title,
                body=body,
                published_at=now - timedelta(hours=index + 1),
            )
        )
        news.save_features(
            NewsFeatures(
                news_id=article.news_id,
                tags=[NewsTag(id=TAG_ID, confidence=1)] if relevant else [],
                geography=Geography(),
                summary=body,
            ),
            version="demo-v1",
            expected_content_hash=article.content_hash,
            expected_published_at=article.published_at,
        )
        ids.append(str(article.news_id))
    return ids


if __name__ == "__main__":
    created = create_demo_data()
    print(f"Demo company: {COMPANY_ID}")
    print(f"Demo news: {len(created)}")
