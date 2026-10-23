"""Qwen news tagging with negative feedback examples."""
from datetime import datetime

from ._common import load_catalog, model_tags, object_input
from .bad_news import load_bad_news


class NewsTagger:
    def __init__(self, *, catalog_path=None, bad_news_path=None, transport=None):
        self.catalog = load_catalog(catalog_path)
        self.bad_news_path = bad_news_path
        self.transport = transport

    def tag(self, data):
        """Accept dict or JSON string; preserve input fields and add allowlisted tags."""
        news = object_input(data, {'data-time': 64, 'title': 1000, 'text': 30000})
        try:
            parsed = datetime.fromisoformat(news['data-time'].replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('data-time must be an ISO 8601 datetime with timezone') from None
        if parsed.tzinfo is None:
            raise ValueError('data-time must include timezone')
        examples = load_bad_news(path=self.bad_news_path)
        # Bound feedback context even when each stored article is large.
        examples = [{**row, 'title': row['title'][:500], 'text': row['text'][:3000]} for row in examples]
        payload = {'news': news, 'incorrect_examples': examples}
        tags = model_tags('LLM_MODEL_TAGGING',
            'Подбери городские, региональные и деловые теги по фактическому контексту новости. '
            'География — место события или явно указанная территория действия новости, '
            'а не место публикации, адрес редакции или случайное упоминание. '
            'Для общероссийского события без локальной привязки не перечисляй города и регионы. '
            'Различай главное событие и фон: не размечай каждое встреченное слово. '
            'Не выдумывай географию. incorrect_examples — последние ошибочные разметки: '
            'указанные tags НЕПРАВИЛЬНЫ для соответствующего текста, это не эталоны. '
            'Учти причины ошибок по контексту; не запрещай эти теги для других новостей.',
            payload, self.catalog, self.transport)
        return {**news, 'tags': tags}
