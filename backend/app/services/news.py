from datetime import datetime
from uuid import UUID

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import TagData
from app.schemas.news import NewsFeatures, StoredNews
from app.schemas.services import IncomingNews

from ._common import required
from .tag_catalog import load_catalog


class NewsService:
    """паттерн Service Layer: сохраняет новости и признаки, возвращает теги и новости для разметки"""

    def __init__(self, *, uow_factory=UnitOfWork):
        """сохраняет фабрику транзакций для операций с новостями

        внедрение зависимостей (Dependency Injection): uow_factory задаёт способ создания UnitOfWork
        """
        self._uow = uow_factory

    def register_source(self, code: str, *, kind: str) -> None:
        """добавляет источник по коду и типу, если его ещё нет"""
        with self._uow() as db:
            db.news.register_source(required(code, "code"), kind=required(kind, "kind"))
            db.commit()

    def register_tag(self, tag_id: str, *, display_name: str) -> None:
        """добавляет тег по ID и названию, если его ещё нет"""
        with self._uow() as db:
            db.news.register_tag(
                required(tag_id, "tag_id"),
                display_name=required(display_name, "display_name"),
            )
            db.commit()

    def list_tags(self) -> list[TagData]:
        """возвращает ID и названия активных тегов для настройки интересов и разметки"""
        with self._uow() as db:
            return db.news.list_tags()

    def separate_event(self, news_id: UUID) -> StoredNews:
        """отменяет объединение публикации и защищает её от повторного автоматического объединения"""
        with self._uow() as db:
            db.events.separate(news_id)
            result = db.news.get(news_id)
            db.commit()
            return result

    def group_existing_news(self, *, days: int = 30, limit: int = 5000) -> int:
        """обрабатывает сохранённые новости короткими транзакциями без повторной разметки и вызовов LLM"""
        from datetime import UTC, timedelta

        if not 1 <= days <= 365 or not 1 <= limit <= 5000:
            raise ValueError("Invalid event grouping window or limit")
        with self._uow() as db:
            ids = db.events.list_recent_ids(
                datetime.now(UTC) - timedelta(days=days), limit
            )
        for news_id in ids:
            with self._uow() as db:
                db.events.assign_id(news_id)
                db.commit()
        return len(ids)

    def sync_tag_catalog(self, *, catalog_path=None) -> int:
        """загружает тематические коды справочника в БД, географию не превращает в темы"""
        catalog = load_catalog(catalog_path)
        with self._uow() as db:
            count = db.news.sync_tag_catalog(catalog["business"])
            db.commit()
            return count

    def mark_tagging_failed(self, news: StoredNews) -> bool:
        """исключает неудачную версию новости из очереди до явного повторного запуска"""
        with self._uow() as db:
            changed = db.news.mark_tagging_failed(
                news.news_id,
                expected_content_hash=news.content_hash,
                expected_published_at=news.published_at,
            )
            db.commit()
            return changed

    def retry_tagging(self, news_id: UUID) -> StoredNews:
        """повторно ставит failed-новость в очередь разметки"""
        with self._uow() as db:
            news = db.news.retry_tagging(news_id)
            db.commit()
            return news

    def save_news(self, article: IncomingNews) -> StoredNews:
        """сохраняет новость от парсера и возвращает её данные в StoredNews

        для повторной загрузки обновляет существующую запись
        при изменении текста или даты сбрасывает разметку
        """
        with self._uow() as db:
            result = db.news.save_news(**article.model_dump())
            db.commit()
            return result

    def get_news(self, news_id: UUID) -> StoredNews:
        """возвращает текст, хэш и признаки новости, для неизвестного ID вызывает LookupError"""
        with self._uow() as db:
            return db.news.get(news_id)

    def list_pending_news(self, *, limit: int = 50) -> list[StoredNews]:
        """возвращает новости без разметки, начиная с загруженных раньше

        не меняет их статус и не закрепляет за конкретным worker
        """
        with self._uow() as db:
            return db.news.list_pending_news(limit=limit)

    def save_features(
        self,
        features: NewsFeatures,
        *,
        version: str,
        expected_content_hash: str,
        expected_published_at: datetime | None = None,
    ) -> StoredNews:
        """сохраняет признаки и ставит ready, если хэш текста совпадает с expected_content_hash

        хэш нужно взять из StoredNews до вызова LLM
        если текст успел измениться, вызывает ValueError
        """
        with self._uow() as db:
            result = db.news.save_features(
                features,
                version=version,
                expected_content_hash=expected_content_hash,
                expected_published_at=expected_published_at,
            )
            db.commit()
            return result
