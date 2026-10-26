"""связывает публикации в события, сохраняя тексты и возможность разделить ошибочную группу"""

from datetime import timedelta

from sqlalchemy import func, select

from app.infrastructure.database.models.news import (
    News,
    NewsAttribution,
    NewsEvent,
    NewsSource,
)
from app.infrastructure.news_matching import (
    MAX_MEMBERS,
    VERSION,
    WINDOW_HOURS,
    same_event,
)
from app.schemas.news import NewsPublication


class EventRepository:
    """паттерн Repository: хранит группы публикаций в той же транзакции, что и новость"""

    def __init__(self, session):
        self._session = session

    def list_recent_ids(self, since, limit):
        """читает ограниченную порцию ID для повторной группировки сохранённых публикаций"""
        return list(
            self._session.scalars(
                select(News.id)
                .where(News.published_at >= since)
                .order_by(News.published_at, News.id)
                .limit(limit)
            )
        )

    def assign_id(self, news_id):
        """загружает публикацию под общей блокировкой и повторяет локальное сопоставление"""
        self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
        article = self._session.get(News, news_id)
        if article is not None:
            self.assign(article)

    def assign(self, article):
        """сравнивает новую версию с ближайшими публикациями, не объединяет группы по цепочке"""
        self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
        current = (
            self._session.get(NewsEvent, article.story_cluster_id)
            if article.story_cluster_id
            else None
        )
        if current and not current.automatic:
            return
        article.story_cluster_id = None
        self._session.flush()
        own_kind = self._session.scalar(
            select(NewsSource.kind).where(NewsSource.code == article.canonical_source)
        )
        window = timedelta(hours=WINDOW_HOURS)
        fields = (
            News.id,
            News.story_cluster_id,
            News.title,
            func.left(News.text, 4000).label("text"),
            News.content_hash,
            News.published_at,
        )
        candidates = list(
            self._session.execute(
                select(*fields)
                .join(NewsSource, NewsSource.code == News.canonical_source)
                .where(
                    News.id != article.id,
                    News.language == article.language,
                    News.published_at.between(
                        article.published_at - window, article.published_at + window
                    ),
                    (NewsSource.kind == "demo")
                    if own_kind == "demo"
                    else (NewsSource.kind != "demo"),
                )
                .order_by(
                    func.abs(
                        func.extract("epoch", News.published_at - article.published_at)
                    ),
                    News.id,
                )
                .limit(300)
            )
        )
        cluster_ids = {
            row.story_cluster_id for row in candidates if row.story_cluster_id
        }
        events, grouped = {}, {}
        if cluster_ids:
            events = {
                event.id: event
                for event in self._session.scalars(
                    select(NewsEvent).where(NewsEvent.id.in_(cluster_ids))
                )
            }
            for member in self._session.execute(
                select(*fields)
                .where(News.story_cluster_id.in_(cluster_ids))
                .order_by(News.id)
            ):
                grouped.setdefault(member.story_cluster_id, []).append(member)
        checked = set()
        for candidate in candidates:
            key = candidate.story_cluster_id or candidate.id
            if key in checked:
                continue
            checked.add(key)
            event = events.get(candidate.story_cluster_id)
            if event and not event.automatic:
                continue
            members = grouped.get(event.id, []) if event else [candidate]
            if len(members) >= MAX_MEMBERS:
                continue
            if not all(
                abs(member.published_at - article.published_at) <= window
                and (
                    (
                        article.content_hash == member.content_hash
                        and len(article.text.strip()) >= 200
                    )
                    or same_event(
                        article.title, article.text, member.title, member.text
                    )
                )
                for member in members
            ):
                continue
            if event is None:
                event = NewsEvent(matching_version=VERSION)
                self._session.add(event)
                self._session.flush()
                self._session.get(News, candidate.id).story_cluster_id = event.id
            article.story_cluster_id = event.id
            self._session.flush()
            return

    def separate(self, news_id):
        """выделяет публикацию в отдельное событие и запрещает автоматическое повторное объединение"""
        self._session.execute(select(func.pg_advisory_xact_lock(684720270)))
        article = self._session.get(News, news_id)
        if article is None:
            raise LookupError("News not found")
        event = NewsEvent(matching_version=VERSION, automatic=False)
        self._session.add(event)
        self._session.flush()
        article.story_cluster_id = event.id
        self._session.flush()

    def publications(self, article):
        """возвращает исходные тексты и ссылки всех участников события в стабильном порядке"""
        members = (
            list(
                self._session.scalars(
                    select(News)
                    .where(News.story_cluster_id == article.story_cluster_id)
                    .order_by(News.id)
                )
            )
            if article.story_cluster_id
            else [article]
        )
        links = {}
        for link in self._session.scalars(
            select(NewsAttribution)
            .where(NewsAttribution.news_id.in_([n.id for n in members]))
            .order_by(NewsAttribution.id)
        ):
            links.setdefault(link.news_id, []).append(link)
        result = []
        for member in members:
            for link in links.get(member.id, [None]):
                result.append(
                    NewsPublication(
                        publication_id=link.id if link else member.id,
                        news_id=member.id,
                        title=member.title,
                        text=member.text,
                        source_url=link.url if link else member.canonical_url,
                        published_at=(link.published_at if link else None)
                        or member.published_at,
                        content_hash=member.content_hash,
                    )
                )
        return result
