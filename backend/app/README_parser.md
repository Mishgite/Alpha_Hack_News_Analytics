# Парсер

Зависимости устанавливаются из `app/requirements.txt` в окружение проекта
Импорты выполняются из `backend` или при отметке `backend` как Sources Root в PyCharm

```python
from app.parser import NewsAggregator, fetch_cbr_news, fetch_open_rss_feeds
```

- `fetch_cbr_news(fetch_full_text=True)`: новости ЦБ
- `fetch_open_rss_feeds(["bbc_business"], fetch_full_text=True)`: новости выбранных RSS
- `NewsAggregator().fetch_autonomous_news()`: открытые RSS и API
- `NewsAggregator(api_keys=...).fetch_news()`: RSS и API, для которых переданы ключи

Результат: список `NewsItem` с полями `source`, `title`, `text`, `url`, `published_at`, `tags`, `language`

`fetch_full_text=True` включает загрузку текста статьи с сайта, при недоступности страницы остаётся анонс. Язык определяется по тексту, неизвестный обозначается `und`

`NewsItem.to_incoming_news()` возвращает Pydantic-модель `IncomingNews` для сервиса хранения. `text` преобразуется в `body`, дата проверяется на наличие часового пояса, ссылка проверяется как HTTP(S). Теги источника не становятся признаками LLM автоматически

Сохранение порции: `NewsPipeline.save_parsed_news(items, source_kind="rss")`. Методы обработки описаны в [справочнике сервисов](../docs/services.md)

Дедупликация внутри порции выполняется по ссылке без фрагмента, независимо от заголовка и источника. Повторный импорт той же ссылки внутри источника обновляет существующую запись БД. Объединение разных ссылок на одно событие требует отдельного решения

Рыночные данные: `NewsAggregator().fetch_market()` и `NewsAggregator().fetch_cbr_fx()`. Их результат не сохраняется через сервис новостей
