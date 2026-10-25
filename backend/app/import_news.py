"""загружает сохранённую подборку новостей и её разметку без повторных запросов к модели"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.news import NewsFeatures, NewsForTagging
from app.schemas.services import IncomingNews
from app.services.ai_agents._common import validate_features
from app.services.news import NewsService
from app.services.tag_catalog import load_catalog

DEFAULT_FILE = (
    Path(__file__).resolve().parents[1] / "data/examples/recent-news-2026-10-25.json"
)


def read_bundle(path):
    """проверяет все записи и привязку сохранённой разметки к тексту и дате до записи в БД"""
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    if bundle.get("schema_version") != 1 or not isinstance(bundle.get("items"), list):
        raise ValueError("Unsupported news bundle")
    catalog = load_catalog()
    urls = set()
    for row in bundle["items"]:
        article = IncomingNews.model_validate(row["article"])
        if not article.url or article.url in urls:
            raise ValueError("Every example must have a unique source URL")
        urls.add(article.url)
        if row.get("features") is not None:
            features = NewsFeatures(news_id=UUID(int=0), **row["features"])
            validate_features(features, catalog)
            content_hash = hashlib.sha256(
                (article.title + "\n" + article.body).encode()
            ).hexdigest()
            if (
                row.get("content_hash") != content_hash
                or row.get("features_published_at") != article.published_at.isoformat()
                or not row.get("tagging_version")
            ):
                raise ValueError("Saved features do not match the article")
    return bundle


def import_bundle(
    path=DEFAULT_FILE, *, limit=None, tag=False, news_service=None, tagger=None
):
    """сохраняет выбранные новости, восстанавливает признаки и при tag размечает только pending"""
    if limit is not None and limit < 1:
        raise ValueError("Limit must be positive")
    bundle = read_bundle(path)
    news = news_service if news_service is not None else NewsService()
    news.sync_tag_catalog()
    ids = []
    for row in bundle["items"][:limit]:
        article = IncomingNews.model_validate(row["article"])
        news.register_source(article.source, kind="curated_summary")
        saved = news.save_news(article)
        if saved.tagging_status != "ready":
            if row.get("features") is not None:
                features = NewsFeatures(news_id=saved.news_id, **row["features"])
                version = row["tagging_version"]
            elif tag:
                if tagger is None:
                    from app.services.ai_agents import NewsTagger

                    tagger = NewsTagger()
                features = tagger.tag(
                    NewsForTagging(
                        **saved.model_dump(include=set(NewsForTagging.model_fields))
                    )
                )
                version = tagger.version
            else:
                ids.append(saved.news_id)
                continue
            saved = news.save_features(
                features,
                version=version,
                expected_content_hash=saved.content_hash,
                expected_published_at=saved.published_at,
            )
        if tag:
            row.update(
                features=saved.features.model_dump(mode="json", exclude={"news_id"}),
                content_hash=saved.content_hash,
                features_published_at=article.published_at.isoformat(),
                tagging_version=saved.tagging_version,
            )
            # сохраняем каждую готовую запись, чтобы после сбоя не оплачивать разметку заново
            output = Path(path)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(output)
        ids.append(saved.news_id)
        print(f"{saved.tagging_status}: {saved.news_id} {saved.title}", flush=True)
    return ids


def main():
    """принимает путь и размер подборки, вызовы модели разрешает только параметр --tag"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--tag",
        action="store_true",
        help="tag pending examples and save features to JSON",
    )
    args = parser.parse_args()
    ids = import_bundle(args.file, limit=args.limit, tag=args.tag)
    print(f"Imported: {len(ids)}")


if __name__ == "__main__":
    main()
