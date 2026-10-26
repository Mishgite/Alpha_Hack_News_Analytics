"""загружает небольшой переносимый набор без исходных CSV и вызовов модели"""

import json
import os
from pathlib import Path

from sqlalchemy import text

from app.import_news import DEFAULT_FILE, read_bundle
from app.infrastructure.database.init_db import initialize_database
from app.infrastructure.database.session import get_engine
from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import CompanyData, CompanyTagInput
from app.schemas.news import NewsFeatures
from app.schemas.reports import ReportInput
from app.schemas.services import IncomingNews
from app.services.profile_pipeline import TAGGING_VERSION
from app.services.tag_catalog import load_catalog

EXAMPLES = Path(__file__).resolve().parents[1] / "data/examples"
SEED_KEY = "bundled_demo_v1"


def read_examples(directory=EXAMPLES):
    """проверяет весь набор до записи, чтобы повреждённый файл не дал частичную загрузку"""
    companies_file = json.loads(
        (directory / "demo-companies.json").read_text(encoding="utf-8")
    )
    reports_file = json.loads(
        (directory / "demo-report-excerpts.json").read_text(encoding="utf-8")
    )
    if (
        companies_file.get("schema_version") != 1
        or reports_file.get("schema_version") != 1
    ):
        raise ValueError("Unsupported demo bundle version")
    companies = [
        (
            CompanyData.model_validate(row["company"]),
            [CompanyTagInput.model_validate(t) for t in row["tags"]],
        )
        for row in companies_file["items"]
    ]
    if len(companies) != 50 or len({c.id for c, _ in companies}) != 50:
        raise ValueError("Demo bundle must contain 50 unique companies")
    active = set(load_catalog()["business"].values())
    for company, tags in companies:
        if not tags or any(t.tag_id not in active for t in tags):
            raise ValueError("Invalid company topics")
    news = read_bundle(directory / DEFAULT_FILE.name)["items"]
    if not news or any(row.get("features") is None for row in news):
        raise ValueError("Demo news must include saved features")
    reports = [ReportInput.model_validate(row) for row in reports_file["reports"]]
    if not reports:
        raise ValueError("Missing report excerpts")
    return companies, news, reports


def seed_demo(*, engine=None, directory=EXAMPLES):
    """добавляет отсутствующие записи одной транзакцией, завершённый импорт повторно не выполняет"""
    engine = engine if engine is not None else get_engine()
    companies, news, reports = read_examples(directory)
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(684720269)")):
            raise RuntimeError("Another bootstrap is running")
        lock.commit()
        try:
            initialize_database(engine)
            with UnitOfWork(engine) as db:
                state = db.runtime.get(SEED_KEY)
                if state and state["value"].get("status") == "ready":
                    print(
                        "Bundled demo already loaded; existing data preserved",
                        flush=True,
                    )
                    return state["value"]
                db.news.sync_tag_catalog(load_catalog()["business"])
                added_companies = added_news = 0
                model = os.environ.get("LLM_MODEL_CONTEXT", "z-ai/glm-5.3-flash")
                for company, tags in companies:
                    if db.companies.get(company.id) is not None:
                        continue
                    db.companies.save(company)
                    db.companies.set_tags(company.id, tags)
                    db.runtime.save(
                        "profile:" + company.id,
                        {
                            "status": "ready",
                            "version": company.profile_version
                            + "|"
                            + TAGGING_VERSION
                            + model,
                            "origin": "bundled_demo",
                        },
                    )
                    added_companies += 1
                for row in news:
                    article = IncomingNews.model_validate(row["article"])
                    if db.news.contains_publication(
                        article.source, article.external_id, article.url
                    ):
                        continue
                    db.news.register_source(article.source, kind="curated_summary")
                    saved = db.news.save_news(**article.model_dump())
                    db.news.save_features(
                        NewsFeatures(news_id=saved.news_id, **row["features"]),
                        version=row["tagging_version"],
                        expected_content_hash=saved.content_hash,
                        expected_published_at=saved.published_at,
                    )
                    added_news += 1
                for report in reports:
                    db.reports.save(report)
                if not db.runtime.get("demo_companies"):
                    db.runtime.save(
                        "demo_companies", {"ids": [c.id for c, _ in companies]}
                    )
                result = {
                    "status": "ready",
                    "mode": "demo",
                    "companies": added_companies,
                    "news": added_news,
                    "reports": len(reports),
                }
                db.runtime.save(SEED_KEY, result)
                db.runtime.save("server_bootstrap_v1", result)
                db.commit()
                print(
                    f"Demo ready: {added_companies} companies, {added_news} news, {len(reports)} reports",
                    flush=True,
                )
                return result
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(684720269)"))
            lock.commit()


if __name__ == "__main__":
    seed_demo()
