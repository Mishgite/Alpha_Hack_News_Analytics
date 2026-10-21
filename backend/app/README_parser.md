# Alfa News Parser

Библиотека для сбора и нормализации новостей и рыночных данных из источников,
описанных в чате «Сравнение источников новостей и данных для вашего Альфа-Хакатона».

Поддерживает два режима:
- **Автономный** — без API-ключей и регистрации (открытые RSS и JSON API).
- **С ключами** — платные/лимитированные API (Currents, NewsData, GNews и др.).

Результат всегда возвращается как обычные переменные Python (`list`, `dict`, `DataFrame`), а не печатается.

---

## 1. Установка

```bash
cd /Users/mihra/PycharmProjects/test_alfa
source .venv/bin/activate
pip install -e .
```

Зависимости (`feedparser`, `httpx`, `pandas`, `pydantic`) устанавливаются автоматически.

---

## 2. Быстрый старт (автономный режим)

```python
from alfa_news_parser import NewsAggregator

# Создаём агрегатор (без ключей)
agg = NewsAggregator()

# Получаем новости — результат в переменную `news`
news = agg.fetch_autonomous_news(
    include_rss=True,                 # включить RSS-ленты
    rss_feeds=["bbc_top", "guardian_world", "hacker_news"],  # или None = все
    include_apis=True,                # включить открытые JSON API
    google_queries=["инфляция"],       # запросы для Google News RSS
    gdelt_query="economy",            # запрос для GDELT
)

print(f"Собрано новостей: {len(news)}")
```

Каждый элемент `news` — объект `NewsItem` со следующими полями:

| Поле | Описание |
|------|----------|
| `title` | **Тема** новости |
| `text` | **Сам текст** (очищенный от HTML) |
| `url` | **Ссылка на первоисточник** |
| `published_at` | **Дата и время** появления новости (ISO-8601 UTC) |
| `source` | Идентификатор источника (например, `bbc_top`) |
| `tags` | Список тегов/категорий |

Пример обращения к полям:

```python
item = news[0]
print(item.title)        # Тема
print(item.text)         # Текст
print(item.url)          # Ссылка на первоисточник
print(item.published_at) # 2026-10-21T15:36:31+00:00
```

---

## 3. Режим с API-ключами

```python
from alfa_news_parser import NewsAggregator

agg = NewsAggregator(api_keys={
    "currents": "YOUR_CURRENTS_KEY",
    "newsdata": "YOUR_NEWSDATA_KEY",
    "gnews": "YOUR_GNEWS_KEY",
    "guardian": "YOUR_GUARDIAN_KEY",
    "marketaux": "YOUR_MARKETAUX_KEY",
    "alphavantage": "YOUR_ALPHAVANTAGE_KEY",
    "finnhub": "YOUR_FINNHUB_KEY",
})

# Собираем из источников с ключами + RSS
news = agg.fetch_news(
    include_rss=True,
    include_api=True,
    google_queries=["инфляция"],
    limit_per_source=50,
    dedup=True,
)
```

Источники без ключа в `api_keys` просто пропускаются (не вызывают ошибку).

---

## 4. Рыночные данные и курсы валют

```python
# Топ движений акций MOEX
market = agg.fetch_market(top_movers=True, limit=10)
# market — list[MarketQuote]: ticker, name, price, change, change_percent, volume, updated_at

for q in market:
    print(q.ticker, q.change_percent, q.url if hasattr(q, "url") else "")

# Курсы валют ЦБ
fx = agg.fetch_cbr_fx()
# fx — list[dict]: char_code, name, value, vunit_rate, ...
print(fx[0])
```

---

## 5. Экспорт в pandas DataFrame

```python
from alfa_news_parser import to_dataframe, to_plain

df = to_dataframe(news)          # pandas.DataFrame
print(df.shape)                  # (N, 7)
print(df[["source", "title", "published_at"]].head())

plain = to_plain(news)           # list[dict] — для JSON/БД
```

---

## 6. Прямые функции (без агрегатора)

Можно вызывать адаптеры напрямую:

```python
from alfa_news_parser import (
    fetch_cbr_news,
    fetch_rss_feed,
    fetch_google_news_rss,
    fetch_moex_top_movers,
    fetch_cbr_fx_rates,
    fetch_open_rss_feeds,
    fetch_hackernews_top,
    fetch_reddit_json,
    fetch_gdelt_articles,
)

cbr_news = fetch_cbr_news()                       # ЦБ RSS
bbc_news = fetch_open_rss_feeds(["bbc_top"])        # BBC RSS
hn = fetch_hackernews_top(limit=20)                # Hacker News
reddit = fetch_reddit_json("worldnews", limit=25)  # Reddit
gdelt = fetch_gdelt_articles("economy", limit=25)  # GDELT
fx = fetch_cbr_fx_rates()                          # курсы ЦБ
market = fetch_moex_top_movers(limit=10)           # MOEX
```

Любой RSS по URL:

```python
items = fetch_rss_feed("https://feeds.bbci.co.uk/news/rss.xml", source="bbc")
```

---

## 7. Доступные автономные RSS-ленты

Словарь `OPEN_RSS_FEEDS` содержит все URL:

```python
from alfa_news_parser import OPEN_RSS_FEEDS
print(list(OPEN_RSS_FEEDS.keys()))
# ['bbc_top', 'bbc_world', 'guardian_world', 'aljazeera', 'sky_news', ...]
```

Полный список: `bbc_top`, `bbc_world`, `bbc_tech`, `bbc_business`, `guardian_world`, `guardian_tech`, `aljazeera`, `sky_news`, `npr`, `cbs`, `wsj_world`, `euronews`, `lemonde_en`, `spiegel_intl`, `times_of_india`, `ndtv`, `abc_australia`, `un_news`, `techcrunch`, `ars_technica`, `the_verge`, `engadget`, `hacker_news`, `nyt_home`, `dw_english`, `fox_latest`, `cnbc`.

---

## 8. Статические данные из чата

Библиотека содержит все таблицы из проанализированного чата как переменные:

```python
from alfa_news_parser import NewsAggregator

agg = NewsAggregator()
v = agg.as_variables()

v["international_sources"]   # 10 международных API
v["russian_sources"]         # 9 российских СМИ
v["gov_sources"]             # 10 гос. источников
v["market_sources"]          # 9 финансовых источников
v["industry_mapping"]        # маппинг отраслей -> источники
v["polling_intervals"]       # рекомендуемые интервалы опроса
v["starter_sources"]         # стартовый набор из 6 источников
```

Или напрямую:

```python
from alfa_news_parser.sources import INTERNATIONAL_SOURCES, POLLING_INTERVALS
```

---

## 9. Нормализация и очистка

- Даты приводятся к ISO-8601 UTC (`normalize_date`).
- HTML-теги удаляются из текста (`strip_html`).
- Дубликаты удаляются по `(source, title, url)` (`deduplicate`).
- Unix timestamps (секунды и миллисекунды) обрабатываются автоматически.

```python
from alfa_news_parser import normalize_date, strip_html, deduplicate

clean_text = strip_html("<p>Привет <b>мир</b></p>")  # "Привет мир"
iso_date = normalize_date(1729500000)                 # "2024-10-21T..."
unique = deduplicate(news_list)                      # удаление дублей
```

---

## 10. Обработка ошибок

- Все сетевые вызовы обёрнуты в `try/except` — один недоступный источник не ломает остальные.
- При отсутствии API-ключа соответствующий адаптер просто пропускается.
- Функции возвращают пустой список при ошибке, а не падают.

---

## 11. Запуск примера

```bash
cd /Users/mihra/PycharmProjects/test_alfa
source .venv/bin/activate
python main.py
```

Вывод:
```
news=207 market=10 fx=54
available variable sets: ['international_sources', 'russian_sources', ...]
sample: Burnham defends Jackdaw decision ... | https://www.bbc.co.uk/... | 2026-10-21T15:36:31+00:00
```

---

## 12. Тесты

```bash
source .venv/bin/activate
pytest -q
# 5 passed
```

---

## Структура проекта

```
alfa_news_parser/
├── __init__.py       # публичный API
├── models.py         # NewsItem, MarketQuote
├── normalize.py      # нормализация дат, очистка, дедупликация, to_dataframe
├── rss.py            # RSS-адаптеры + курсы ЦБ
├── api.py            # API с ключами
├── moex.py           # MOEX ISS
├── autonomous.py     # автономные источники без ключей
├── aggregator.py     # NewsAggregator
└── sources.py        # статические данные из чата
tests/
└── test_basic.py
main.py               # пример использования
README.md
pyproject.toml
```