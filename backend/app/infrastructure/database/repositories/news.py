import hashlib
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    News,
    NewsAttribution,
    NewsSource,
    NewsTag,
    Tag,
)
from app.schemas.database import TagData
from app.schemas.news import NewsFeatures, NewsForTagging, StoredNews
from app.schemas.ranking import NewsCandidate

from .events import EventRepository


class NewsRepository:
    """паттерн Repository: читает и записывает новости, источники, теги и признаки

    возвращает DTO, транзакцией управляет вызывающий код
    """

    def __init__(self, session: Session):
        """внедрение зависимостей (Dependency Injection): получает готовую сессию от UnitOfWork"""
        self._session = session

    def contains_publication(self, source, external_id, url):
        """проверяет основные и дополнительные ссылки, чтобы импорт примеров не заменял рабочие новости"""
        keys = []
        if url:
            keys.append(NewsAttribution.url == url)
        if external_id:
            keys.append(
                (NewsAttribution.source_code == source)
                & (NewsAttribution.external_id == external_id)
            )
        if keys and self._session.scalar(
            select(NewsAttribution.id).where(or_(*keys)).limit(1)
        ):
            return True
        keys = []
        if url:
            keys.append(News.canonical_url == url)
        if external_id:
            keys.append(
                (News.source_code == source) & (News.external_id == external_id)
            )
        return bool(
            keys and self._session.scalar(select(News.id).where(or_(*keys)).limit(1))
        )

    def save_news(
        self,
        *,
        source: str,
        external_id: str | None,
        url: str | None,
        title: str,
        body: str,
        published_at: datetime,
        language: str = "ru",
    ) -> StoredNews:
        """находит новость по внешнему ID или URL внутри источника и создаёт либо обновляет запись

        блокирует источник до конца транзакции, чтобы избежать повторных вставок
        при изменении текста или даты сбрасывает разметку
        """
        if not external_id and not url:
            raise ValueError("external_id or url is required")
        if not title.strip() or published_at.tzinfo is None:
            raise ValueError("Title and timezone-aware publication time are required")
        # общая блокировка не даёт двум источникам одновременно сохранить одинаковый текст
        self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
        registered = self._session.scalar(
            select(NewsSource).where(NewsSource.code == source).with_for_update()
        )
        if registered is None:
            raise LookupError("News source not registered")
        if not registered.enabled:
            raise ValueError("News source is disabled")
        url_hash = hashlib.sha256(url.encode()).hexdigest() if url else None
        keys = []
        if external_id:
            keys.append(News.external_id == external_id)
        if url_hash:
            keys.append(News.url_hash == url_hash)
        matches = list(
            self._session.scalars(
                select(News)
                .where(News.canonical_source == source, or_(*keys))
                .with_for_update()
            )
        )
        # если id и ссылка указывают на разные записи, автоматически объединять их нельзя
        if len(matches) > 1:
            raise ValueError("External ID and URL refer to different articles")
        content_hash = hashlib.sha256((title + "\n" + body).encode()).hexdigest()
        record = matches[0] if matches else News(canonical_source=source)
        changed = (
            record.content_hash != content_hash or record.published_at != published_at
        )
        if (
            matches
            and record.external_id
            and external_id
            and record.external_id != external_id
        ):
            raise ValueError("URL already belongs to another external ID")
        record.external_id = external_id or record.external_id
        record.canonical_url = url or record.canonical_url
        record.url_hash = url_hash or record.url_hash
        record.title, record.text = title, body
        record.published_at, record.language = published_at, language
        record.content_hash = content_hash
        # признаки старого текста больше не подходят: новость должна пройти разметку заново
        if changed:
            record.tagging_status = "pending_tagging"
            record.tagging_version = None
            record.extracted_features = None
            record.summary = None
        self._session.add(record)
        self._session.flush()
        if changed:
            self._session.execute(delete(NewsTag).where(NewsTag.news_id == record.id))
        if url:
            self._save_attribution(record.id, source, external_id, url, published_at)
        self._session.flush()
        if changed:
            EventRepository(self._session).assign(record)
            self._reuse_features(record)
        return self.get(record.id)

    def _save_attribution(self, news_id, source, external_id, url, published_at):
        """сохраняет ссылку на публикацию, обновлённую копию связывает с её новым текстом"""
        same_url = self._session.scalar(
            select(NewsAttribution).where(
                NewsAttribution.news_id == news_id, NewsAttribution.url == url
            )
        )
        if same_url is not None and same_url.source_code != source:
            return
        attribution = (
            self._session.scalar(
                select(NewsAttribution).where(
                    NewsAttribution.source_code == source,
                    NewsAttribution.external_id == external_id,
                )
            )
            if external_id
            else None
        )
        if attribution is None:
            attribution = self._session.scalar(
                select(NewsAttribution).where(
                    NewsAttribution.source_code == source, NewsAttribution.url == url
                )
            )
        if attribution is None:
            attribution = NewsAttribution(news_id=news_id, source_code=source, url=url)
        attribution.news_id = news_id
        attribution.url = url
        attribution.external_id = external_id or attribution.external_id
        attribution.published_at = published_at
        self._session.add(attribution)

    @staticmethod
    def _dto(row: News) -> StoredNews:
        # читаем нужные поля здесь; после закрытия сессии DTO не понадобится доступ к БД
        """собирает StoredNews из ORM-записи; признаки включает только для статуса ready"""
        return StoredNews(
            news_id=row.id,
            title=row.title,
            text=row.text,
            published_at=row.published_at,
            source_url=row.canonical_url,
            content_hash=row.content_hash,
            tagging_status=row.tagging_status,
            tagging_version=row.tagging_version,
            features=NewsFeatures.model_validate(row.extracted_features)
            if row.tagging_status == "ready"
            else None,
        )

    def get(self, news_id: UUID, *, lock: bool = False) -> StoredNews:
        """возвращает StoredNews либо вызывает LookupError; lock удерживает строку до завершения транзакции"""
        query = (
            select(News)
            .where(News.id == news_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
            query = query.with_for_update()
        row = self._session.scalar(query)
        if row is None:
            raise LookupError("News not found")
        result = self._dto(row)
        result.event_id = row.story_cluster_id
        result.publications = EventRepository(self._session).publications(row)
        return result

    def list_tags(self) -> list[TagData]:
        """возвращает ID и названия активных тегов в порядке ID"""
        rows = self._session.scalars(select(Tag).where(Tag.active).order_by(Tag.id))
        return [TagData.model_validate(row) for row in rows]

    def unique_events(self, items):
        """оставляет первую публикацию каждого события в уже рассчитанном порядке рейтинга"""
        self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
        groups = dict(
            self._session.execute(
                select(News.id, News.story_cluster_id).where(
                    News.id.in_([item.news_id for item in items])
                )
            ).all()
        )
        seen, result = set(), []
        for item in items:
            event = groups.get(item.news_id) or item.news_id
            if event not in seen:
                result.append(item)
                seen.add(event)
        return result

    def list_pending_news(self, *, limit: int = 50) -> list[StoredNews]:
        """читает порцию pending_tagging по времени загрузки, не блокируя её за разметчиком"""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be in [1, 500]")
        rows = self._session.scalars(
            select(News)
            .where(
                News.tagging_status == "pending_tagging",
            )
            .order_by(News.fetched_at, News.id)
            .limit(limit)
        )
        unique, seen = [], {}
        for row in rows:
            key = (row.content_hash, row.language)
            if not any(
                abs(row.published_at - date) <= timedelta(days=2)
                for date in seen.get(key, [])
            ):
                unique.append(self._dto(row))
                seen.setdefault(key, []).append(row.published_at)
        return unique

    def check_candidates(self, expected: list[NewsCandidate]) -> None:
        # проверяем именно признаки, использованные ранжировщиком, и удерживаем строки до сохранения ленты
        """сверяет даты, признаки и веса тегов с данными, которые получил ранжировщик

        при изменениях вызывает ValueError
        блокирует новости до конца транзакции
        """
        ids = [item.features.news_id for item in expected]
        rows = {
            row.id: row
            for row in self._session.scalars(
                select(News)
                .where(
                    News.id.in_(ids),
                )
                .order_by(News.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        }
        for item in expected:
            row = rows.get(item.features.news_id)
            if (
                row is None
                or row.tagging_status != "ready"
                or row.published_at != item.published_at
                or NewsFeatures.model_validate(row.extracted_features) != item.features
            ):
                raise ValueError("News features changed; rebuild the feed")
        weights = {}
        for row in self._session.scalars(
            select(NewsTag).where(NewsTag.news_id.in_(ids))
        ):
            weights.setdefault(row.news_id, {})[row.tag_id] = float(row.quality_weight)
        if any(
            weights.get(item.features.news_id, {}) != item.tag_quality_weights
            for item in expected
        ):
            raise ValueError("News quality weights changed; rebuild the feed")

    def get_for_tagging(self, news_id: UUID) -> NewsForTagging:
        """возвращает текст, заголовок, дату и источник в NewsForTagging без служебных полей БД"""
        row = self.get(news_id)
        return NewsForTagging(
            **row.model_dump(include=set(NewsForTagging.model_fields))
        )

    def register_source(self, code: str, *, kind: str) -> None:
        """вставляет источник, если его код ещё не зарегистрирован; существующие данные не обновляет"""
        self._session.execute(
            insert(NewsSource)
            .values(code=code, kind=kind)
            .on_conflict_do_nothing(index_elements=["code"])
        )

    def register_tag(self, tag_id: str, *, display_name: str) -> None:
        """вставляет тег, если ID ещё не зарегистрирован; существующие данные не обновляет"""
        self._session.execute(
            insert(Tag)
            .values(id=tag_id, display_name=display_name)
            .on_conflict_do_nothing(index_elements=["id"])
        )

    def sync_tag_catalog(self, topics: dict[str, str]) -> int:
        """добавляет темы и обновляет названия, не удаляет теги и не включает отключённые"""
        if not topics:
            return 0
        statement = insert(Tag).values(
            [
                {"id": code, "display_name": name, "category": "business"}
                for name, code in topics.items()
            ]
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[Tag.id],
                set_={
                    "display_name": statement.excluded.display_name,
                    "category": "business",
                },
            )
        )
        return len(topics)

    def mark_tagging_failed(
        self,
        news_id: UUID,
        *,
        expected_content_hash: str,
        expected_published_at: datetime,
    ) -> bool:
        """отмечает ошибку только для той версии новости, которая была передана разметчику"""
        row = self._session.scalar(
            select(News).where(News.id == news_id).with_for_update()
        )
        if row is None:
            raise LookupError("News not found")
        if (
            row.content_hash != expected_content_hash
            or row.published_at != expected_published_at
            or row.tagging_status != "pending_tagging"
        ):
            return False
        row.tagging_status = "failed"
        self._session.flush()
        return True

    def retry_tagging(self, news_id: UUID) -> StoredNews:
        """возвращает неудачную разметку в очередь, готовые новости не меняет"""
        row = self._session.scalar(
            select(News).where(News.id == news_id).with_for_update()
        )
        if row is None:
            raise LookupError("News not found")
        if row.tagging_status == "failed":
            row.tagging_status = "pending_tagging"
            self._session.flush()
        return self._dto(row)

    def save_features(
        self,
        features: NewsFeatures,
        *,
        version: str,
        expected_content_hash: str,
        expected_published_at: datetime | None = None,
    ) -> StoredNews:
        """проверяет версию, активность тегов и хэш текста, затем полностью заменяет разметку

        возвращает StoredNews со статусом ready; пустой список тегов допустим
        """
        if not version.strip():
            raise ValueError("Tagger version required")
        ids = [tag.id for tag in features.tags]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate tags")
        valid = set(
            self._session.scalars(select(Tag.id).where(Tag.id.in_(ids), Tag.active))
        )
        if valid != set(ids):
            raise ValueError("Unknown or inactive tag")
        self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
        row = self._session.scalar(
            select(News).where(News.id == features.news_id).with_for_update()
        )
        if row is None:
            raise LookupError("News not found")
        # пока разметчик работал, парсер мог обновить текст; ответ для старой версии не сохраняем
        if row.content_hash != expected_content_hash or (
            expected_published_at is not None
            and row.published_at != expected_published_at
        ):
            raise ValueError("Article changed while it was being tagged")
        # полностью заменяем разметку в одной транзакции; пустой набор тоже допустим
        self._session.execute(delete(NewsTag).where(NewsTag.news_id == row.id))
        self._session.add_all(
            [
                NewsTag(
                    news_id=row.id,
                    tag_id=tag.id,
                    llm_confidence=tag.confidence,
                    tagger_version=version,
                )
                for tag in features.tags
            ]
        )
        row.tagging_version, row.tagging_status = version, "ready"
        row.extracted_features = features.model_dump(mode="json")
        row.summary = features.summary
        self._session.flush()
        copies = self._session.scalars(
            select(News).where(
                News.id != row.id,
                News.content_hash == row.content_hash,
                News.language == row.language,
                News.tagging_status == "pending_tagging",
                News.published_at.between(
                    row.published_at - timedelta(days=2),
                    row.published_at + timedelta(days=2),
                ),
            )
        )
        for copy in copies:
            self._reuse_features(copy, original=row)
        self._session.flush()
        return self.get(row.id)

    def _reuse_features(self, row, *, original=None):
        """копирует готовую разметку только дословного текста того же языка и близкой даты"""
        if original is None:
            original = self._session.scalar(
                select(News)
                .where(
                    News.id != row.id,
                    News.content_hash == row.content_hash,
                    News.language == row.language,
                    News.tagging_status == "ready",
                    News.published_at.between(
                        row.published_at - timedelta(days=2),
                        row.published_at + timedelta(days=2),
                    ),
                )
                .order_by(News.id)
                .limit(1)
            )
        if original is None:
            return
        features = NewsFeatures.model_validate(original.extracted_features).model_copy(
            update={"news_id": row.id}
        )
        row.extracted_features = features.model_dump(mode="json")
        row.tagging_status, row.tagging_version, row.summary = (
            "ready",
            original.tagging_version,
            original.summary,
        )
        self._session.execute(delete(NewsTag).where(NewsTag.news_id == row.id))
        for tag in self._session.scalars(
            select(NewsTag).where(NewsTag.news_id == original.id)
        ):
            self._session.add(
                NewsTag(
                    news_id=row.id,
                    tag_id=tag.tag_id,
                    llm_confidence=tag.llm_confidence,
                    tagger_version=tag.tagger_version,
                )
            )
        self._session.flush()

    def list_candidates(
        self,
        *,
        since: datetime,
        as_of: datetime,
        limit: int = 500,
        include_demo: bool = False,
    ) -> list[NewsCandidate]:
        """возвращает размеченные новости от новых к старым

        дата публикации должна быть между since и as_of, дата загрузки не позднее as_of
        каждая новость содержит признаки и веса качества тегов
        """
        if (
            since.tzinfo is None
            or as_of.tzinfo is None
            or since > as_of
            or not 1 <= limit <= 5000
        ):
            raise ValueError("Invalid candidate window or limit")
        rows = list(
            self._session.scalars(
                select(News)
                .where(
                    News.tagging_status == "ready",
                    News.published_at >= since,
                    News.published_at <= as_of,
                    News.fetched_at <= as_of,
                    True
                    if include_demo
                    else News.canonical_source.not_in(
                        select(NewsSource.code).where(NewsSource.kind == "demo")
                    ),
                )
                .order_by(News.published_at.desc(), News.id.desc())
                .limit(limit)
            )
        )
        # загружаем веса всех кандидатов одним запросом, без отдельного запроса для каждой новости
        weights = {}
        if rows:
            for tag in self._session.scalars(
                select(NewsTag).where(
                    NewsTag.news_id.in_([row.id for row in rows]),
                )
            ):
                weights.setdefault(tag.news_id, {})[tag.tag_id] = float(
                    tag.quality_weight
                )
        return [
            NewsCandidate(
                published_at=row.published_at,
                features=NewsFeatures.model_validate(row.extracted_features),
                tag_quality_weights=weights.get(row.id, {}),
            )
            for row in rows
        ]
