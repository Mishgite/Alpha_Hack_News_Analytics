"""проверяет загрузку переносимого набора и сохранность данных при повторном запуске"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app import seed_demo, test_backend
from app.infrastructure.database.repositories.analytics import ReportRepository
from app.infrastructure.database.uow import UnitOfWork
from app.schemas.services import Registration
from app.services.feed import FeedService
from app.services.profile_policy import default_policy
from app.services.profiles import ProfileService
from app.services.ranking import rank_news

database = test_backend.database


def test_bundle_has_only_shareable_company_fields():
    companies, news, reports = seed_demo.read_examples()
    assert len(companies) == 50 and len(news) == 104 and len(reports) == 9
    for company, tags in companies:
        assert company.revenue is None and company.group_id is None
        assert set(company.profile_json) == {"demo_export", "revenue_band"}
        assert tags
    assert all(row["article"]["url"].startswith("https://") for row in news)


def test_incomplete_bundle_rejected(tmp_path):
    for source in seed_demo.EXAMPLES.glob("*.json"):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    path = tmp_path / "demo-companies.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["items"].pop()
    path.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(ValueError, match="50 unique"):
        seed_demo.read_examples(tmp_path)


def test_seed_is_atomic_repeatable_and_feeds_all_companies(database, monkeypatch):
    monkeypatch.setattr(seed_demo, "initialize_database", lambda engine: None)
    companies_bundle, news_bundle, reports_bundle = seed_demo.read_examples()
    latest = max(
        datetime.fromisoformat(row["article"]["published_at"]) for row in news_bundle
    )
    shift = datetime.now(UTC) - timedelta(hours=1) - latest
    for row in news_bundle:
        date = datetime.fromisoformat(row["article"]["published_at"]) + shift
        row["article"]["published_at"] = date.isoformat()
        row["features_published_at"] = date.isoformat()
    monkeypatch.setattr(
        seed_demo,
        "read_examples",
        lambda directory: (companies_bundle, news_bundle, reports_bundle),
    )
    with (
        patch.object(
            ReportRepository, "save", side_effect=ValueError("interrupted import")
        ),
        pytest.raises(ValueError, match="interrupted"),
    ):
        seed_demo.seed_demo(engine=database)
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
        assert connection.scalar(text("SELECT count(*) FROM news")) == 0
        assert connection.scalar(text("SELECT count(*) FROM processing_states")) == 0

    first = seed_demo.seed_demo(engine=database)
    assert first == {
        "status": "ready",
        "mode": "demo",
        "companies": 50,
        "news": 104,
        "reports": 9,
    }
    with database.begin() as connection:
        connection.execute(
            text(
                "UPDATE companies SET industry = 'Изменено пользователем' WHERE id = 'U_106783'"
            )
        )
        connection.execute(
            text(
                "UPDATE news SET title = 'Изменено пользователем' WHERE id = (SELECT id FROM news LIMIT 1)"
            )
        )
    assert seed_demo.seed_demo(engine=database) == first
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM news")) == 104
        assert (
            connection.scalar(
                text("SELECT count(*) FROM news WHERE tagging_status = 'ready'")
            )
            == 104
        )
        assert (
            connection.scalar(
                text("SELECT industry FROM companies WHERE id = 'U_106783'")
            )
            == "Изменено пользователем"
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM news WHERE title = 'Изменено пользователем'")
            )
            == 1
        )

    def uow():
        return UnitOfWork(database)

    profiles = ProfileService(uow_factory=uow, policy=default_policy())
    feed = FeedService(ranker=rank_news, uow_factory=uow, policy=default_policy())
    companies = profiles.list_companies(limit=100, demo_selection=True)
    assert len(companies) == 50
    selections = set()
    for company in companies:
        grant = profiles.register_demo(
            Registration(company_id=company.id, job_role="ceo")
        )
        page = feed.create_feed(grant.user.id, days=30, page_size=5)
        assert page.items, company.id
        selections.add(tuple(str(item.ranking.news_id) for item in page.items))
    assert len(selections) >= 10
