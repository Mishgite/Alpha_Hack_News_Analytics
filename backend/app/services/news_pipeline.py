"""связывает результаты парсера, разметчик и сервис хранения новостей"""

import logging

from app.schemas.news import NewsForTagging
from app.schemas.tagging import ProcessingError, ProcessingResult

from .news import NewsService

logger = logging.getLogger(__name__)


class NewsPipeline:
    """паттерн Service Layer: выполняет загрузку и разметку через отдельные компоненты"""

    def __init__(self, *, news_service=None, tagger=None):
        """внедрение зависимостей: принимает сервис и разметчик для обычного запуска или проверки"""
        self.news = news_service if news_service is not None else NewsService()
        self.tagger = tagger

    def save_parsed_news(self, items, *, source_kind: str) -> ProcessingResult:
        """проверяет новости парсера и сохраняет каждую отдельно, возвращает ошибки по позициям"""
        if not source_kind.strip():
            raise ValueError("Source kind is required")
        result = ProcessingResult()
        for position, item in enumerate(items):
            try:
                article = item.to_incoming_news()
                self.news.register_source(article.source, kind=source_kind)
                saved = self.news.save_news(article)
                if saved.news_id not in result.news_ids:
                    result.news_ids.append(saved.news_id)
            except (ValueError, LookupError) as error:
                result.errors.append(
                    ProcessingError(position=position, code=type(error).__name__)
                )
                logger.warning(
                    "News import failed: position=%s error=%s",
                    position,
                    type(error).__name__,
                )
        return result

    def tag_pending_news(self, *, limit: int = 50) -> ProcessingResult:
        """размечает порцию новостей без открытой сессии БД во время запроса к LLM"""
        if self.tagger is None:
            from .ai_agents import NewsTagger

            self.tagger = NewsTagger()
        self.tagger.check_configuration()
        result = ProcessingResult()
        for article in self.news.list_pending_news(limit=limit):
            try:
                data = NewsForTagging(
                    **article.model_dump(include=set(NewsForTagging.model_fields))
                )
                features = self.tagger.tag(data)
                if features.news_id != article.news_id:
                    raise ValueError("Tagger returned another news ID")
                self.news.save_features(
                    features,
                    version=self.tagger.version,
                    expected_content_hash=article.content_hash,
                    expected_published_at=article.published_at,
                )
                result.news_ids.append(article.news_id)
            except (ValueError, RuntimeError, OSError) as error:
                self.news.mark_tagging_failed(article)
                result.errors.append(
                    ProcessingError(news_id=article.news_id, code=type(error).__name__)
                )
                logger.warning(
                    "News tagging failed: news_id=%s error=%s",
                    article.news_id,
                    type(error).__name__,
                )
        return result
