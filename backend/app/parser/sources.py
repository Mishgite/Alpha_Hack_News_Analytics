"""Static data extracted from the analysed chat, exposed as Python variables."""

from __future__ import annotations

from typing import Any, Dict, List

INTERNATIONAL_SOURCES: List[Dict[str, str]] = [
    {"name": "NewsAPI.org", "topics": "Бизнес, политика, технологии, мировые СМИ", "free_access": "100 запросов/сутки, задержка 24 часа", "python": "newsapi-python, httpx", "frequency": "1–3 ч", "rating": "Для разработки"},
    {"name": "Currents API", "topics": "Экономика, политика, технологии, разные страны", "free_access": "250 запросов/сутки, свежие новости", "python": "httpx", "frequency": "15–60 мин", "rating": "Отлично"},
    {"name": "NewsData.io", "topics": "Разные отрасли, бизнес, финансы, международные события", "free_access": "200 кредитов/сутки, до 10 статей за кредит; задержка 12 часов", "python": "newsdataapi, httpx", "frequency": "1–3 ч", "rating": "Отлично"},
    {"name": "GNews API", "topics": "Мировые новости, экономика, технологии, политика", "free_access": "100 запросов/сутки, до 10 статей, задержка 12 часов", "python": "httpx", "frequency": "1–3 ч", "rating": "Хорошо"},
    {"name": "Mediastack", "topics": "Общемировые и деловые новости", "free_access": "100 запросов/месяц, данные с задержкой", "python": "httpx", "frequency": "8–12 ч", "rating": "Слабый бесплатный тариф"},
    {"name": "The Guardian API", "topics": "Экономика, энергетика, политика, технологии, экология", "free_access": "500 запросов/сутки, до 1 запроса/сек, полный текст по условиям лицензии", "python": "httpx", "frequency": "15–60 мин", "rating": "Отлично"},
    {"name": "New York Times API", "topics": "Экономика, мировая политика, технологии, бизнес", "free_access": "API-ключ; лимиты и права уточняются при подключении", "python": "pynytimes, httpx", "frequency": "1–4 ч", "rating": "Дополнительно"},
    {"name": "Marketaux", "topics": "Финансы, компании, акции, инвестиции", "free_access": "100 запросов/сутки, 3 статьи за запрос, свежие данные", "python": "httpx", "frequency": "30–60 мин", "rating": "Отлично"},
    {"name": "Alpha Vantage", "topics": "Финансовые события, акции, валюты, настроения рынка", "free_access": "25 запросов/сутки обычно; отдельные данные платные", "python": "alpha_vantage, httpx", "frequency": "2–4 ч", "rating": "Для финансов"},
    {"name": "GDELT", "topics": "События по всему миру, политика, экономика, конфликты, компании", "free_access": "Открытые данные и API с ограничением частоты", "python": "httpx, pandas", "frequency": "15–60 мин", "rating": "Для аналитики"},
]

RUSSIAN_SOURCES: List[Dict[str, str]] = [
    {"name": "Ведомости — RSS", "topics": "Экономика, отрасли, финансы, недвижимость, IT", "access": "Официальный RSS", "python": "feedparser", "frequency": "15–30 мин", "notes": "Лучший тематический выбор"},
    {"name": "Коммерсантъ — RSS", "topics": "Бизнес, экономика, политика, промышленность", "access": "RSS", "python": "feedparser", "frequency": "15–30 мин", "notes": "Много российских деловых новостей"},
    {"name": "РБК", "topics": "Бизнес, экономика, финансы, компании", "access": "Лицензируемый сбор", "python": "По договору", "frequency": "По договору", "notes": "Автоматический сбор запрещён без разрешения"},
    {"name": "ТАСС — B2B-ленты", "topics": "Практически все категории, включая отраслевые и региональные", "access": "API, RSS, FTP по условиям доступа", "python": "httpx, feedparser", "frequency": "По договору", "notes": "Профессиональные новостные продукты"},
    {"name": "ТАСС — публичный сайт", "topics": "Экономика, регионы, политика, общество, промышленность", "access": "Публичная RSS-лента; условия использования отдельно", "python": "feedparser", "frequency": "15–60 мин*", "notes": "Много разных событий"},
    {"name": "Интерфакс", "topics": "Корпоративные события, экономика, финансы, право", "access": "Коммерческие информационные продукты", "python": "По согласованию", "frequency": "По договору", "notes": "Особенно интересен для крупных компаний"},
    {"name": "РИА Новости", "topics": "Общие, политические, региональные и экономические новости", "access": "RSS/доступность и лицензия требуют проверки", "python": "feedparser при наличии RSS", "frequency": "30–60 мин*", "notes": "Широкое покрытие"},
    {"name": "Google Новости — RSS", "topics": "Новости по ключевым словам и темам", "access": "RSS-поиск, без отдельного API-ключа", "python": "feedparser", "frequency": "30–60 мин", "notes": "Удобно находить упоминания компаний"},
    {"name": "MAX — Bot API", "topics": "Темы каналов, к которым предоставлен доступ", "access": "Bot API", "python": "httpx", "frequency": "5–15 мин*", "notes": "Для получения ленты бот должен иметь необходимые права"},
]

GOV_SOURCES: List[Dict[str, str]] = [
    {"name": "Банк России", "topics": "Ставка, регулирование, банковский рынок, курсы валют", "access": "Официальный RSS", "python": "feedparser", "frequency": "15–30 мин"},
    {"name": "Росстат", "topics": "Инфляция, ВВП, зарплаты, промышленность, занятость", "access": "RSS на сайте, статистические публикации", "python": "feedparser, pandas", "frequency": "6–12 ч"},
    {"name": "ФНС", "topics": "Налоги, отчётность, налоговые изменения", "access": "RSS на сайте, открытые данные", "python": "feedparser, httpx", "frequency": "6–12 ч"},
    {"name": "Минфин России", "topics": "Бюджет, госдолг, налоговая политика", "access": "Официальные публикации, документы", "python": "httpx при разрешённом доступе", "frequency": "6–12 ч"},
    {"name": "ФАС России", "topics": "Тарифы, конкуренция, антимонопольные решения", "access": "Публикации на сайте", "python": "httpx при разрешённом доступе", "frequency": "6–12 ч"},
    {"name": "Минэкономразвития", "topics": "Прогнозы, экономическая политика, инвестиции", "access": "Публикации и документы", "python": "httpx при разрешённом доступе", "frequency": "1–2 раза/день"},
    {"name": "ФТС", "topics": "Таможенное регулирование, импорт, экспорт", "access": "Публикации на сайте", "python": "httpx при разрешённом доступе", "frequency": "1–2 раза/день"},
    {"name": "Официальное опубликование правовых актов", "topics": "Новые законы, указы, постановления", "access": "Официальные документы и PDF", "python": "httpx, PyMuPDF", "frequency": "6–12 ч"},
    {"name": "ЕИС Закупки", "topics": "Госзакупки, контракты, конкурсные процедуры", "access": "Официальные данные; способы интеграции и права проверяются отдельно", "python": "XML/httpx", "frequency": "1–2 раза/день"},
    {"name": "Федресурс", "topics": "Банкротства, существенные факты, сведения об организациях", "access": "Доступ по условиям сервиса", "python": "httpx при согласовании", "frequency": "1 раз/день"},
]

MARKET_SOURCES: List[Dict[str, str]] = [
    {"name": "MOEX ISS API", "topics": "Российские акции, облигации, котировки, свечи, обороты", "python": "REST JSON, httpx, pandas", "frequency": "5–15 мин", "priority": "Обязательно"},
    {"name": "ЦБ — валютные курсы", "topics": "Официальные курсы валют", "python": "RSS, feedparser", "frequency": "1 раз/день", "priority": "Высокий"},
    {"name": "Marketaux", "topics": "Финансовые новости, тикеры, рыночные события", "python": "REST JSON, httpx", "frequency": "30–60 мин", "priority": "Высокий"},
    {"name": "Finnhub", "topics": "Акции, корпоративные события, финансовые новости", "python": "finnhub-python", "frequency": "По тарифу", "priority": "Дополнительно"},
    {"name": "Alpha Vantage", "topics": "Цены, новости, индикаторы, sentiment", "python": "alpha_vantage", "frequency": "1–4 ч", "priority": "Дополнительно"},
    {"name": "EIA", "topics": "Нефть, газ, электроэнергия, энергетика", "python": "Бесплатный REST API с ключом, httpx", "frequency": "1–2 раза/день", "priority": "Для энергетики"},
    {"name": "FRED", "topics": "Инфляция, ставки, ВВП, безработица, макроэкономика", "python": "REST API, fredapi", "frequency": "1–2 раза/день", "priority": "Для макроаналитики"},
    {"name": "ЕЦБ — Data API", "topics": "Курсы валют, европейская экономика", "python": "REST/SDMX, pandas", "frequency": "1–2 раза/день", "priority": "Для международного бизнеса"},
    {"name": "Eurostat", "topics": "Европейская промышленность, торговля, цены", "python": "Бесплатный REST API, httpx", "frequency": "1–2 раза/день", "priority": "Для международного бизнеса"},
]

INDUSTRY_MAPPING: List[Dict[str, str]] = [
    {"industry": "Банки и финансы", "sources": "ЦБ, MOEX, Ведомости/Финансы", "tags": "Ставки, ликвидность, кредитование, инфляция"},
    {"industry": "Строительство", "sources": "Ведомости/Недвижимость, Росстат, ФНС", "tags": "Ипотека, материалы, строительные нормы, финансирование"},
    {"industry": "Нефть и газ", "sources": "EIA, Ведомости/ТЭК, MOEX", "tags": "Нефть, газ, экспорт, тарифы, энергоносители"},
    {"industry": "Транспорт и логистика", "sources": "Ведомости/Транспорт, ФТС, ТАСС", "tags": "Перевозки, пошлины, торговые маршруты, топливо"},
    {"industry": "Сельское хозяйство", "sources": "Ведомости/Агропром, Росстат", "tags": "Урожай, продовольствие, экспорт, цены на сырьё"},
    {"industry": "Промышленность", "sources": "Ведомости/Промышленность, ФАС, Росстат", "tags": "Производство, сырьё, тарифы, оборудование"},
    {"industry": "Ритейл", "sources": "Ведомости/Торговля, Росстат", "tags": "Потребление, цены, импорт, спрос"},
    {"industry": "IT и телеком", "sources": "Ведомости/Технологии, The Guardian, Currents", "tags": "AI, кибербезопасность, регулирование, инфраструктура"},
    {"industry": "Экспортно-импортный бизнес", "sources": "ФТС, ЦБ, GDELT, международные API", "tags": "Валюты, внешняя торговля, санкции, пошлины"},
    {"industry": "Универсальные события", "sources": "Currents, NewsData.io, ЦБ, Ведомости", "tags": "Общая экономика, политика, налоги, рынки"},
]

POLLING_INTERVALS: List[Dict[str, Any]] = [
    {"module": "Currents API", "interval": "30 мин", "requests_per_day": 48},
    {"module": "NewsData.io", "interval": "60 мин", "requests_per_day": 24},
    {"module": "Marketaux", "interval": "60 мин", "requests_per_day": 24},
    {"module": "Ведомости RSS", "interval": "30 мин", "requests_per_day": "48 на канал"},
    {"module": "ЦБ RSS", "interval": "15 мин", "requests_per_day": "96 на канал"},
    {"module": "Росстат RSS", "interval": "6 ч", "requests_per_day": 4},
    {"module": "MOEX ISS", "interval": "10 мин в торговые часы", "requests_per_day": "Зависит от торгового расписания"},
    {"module": "Новости законодательства", "interval": "12 ч", "requests_per_day": 2},
    {"module": "Аналитика Альфа-Банка", "interval": "1 раз/день", "requests_per_day": "По файловому источнику"},
]

VEDOMOSTI_RSS_CHANNELS: List[Dict[str, str]] = [
    {"category": "Все новости", "slug": "news"},
    {"category": "Общая экономика", "slug": "economics"},
    {"category": "Макроэкономика", "slug": "macroeconomics"},
    {"category": "Промышленность", "slug": "industry"},
    {"category": "Нефть, газ, энергетика", "slug": "fuel"},
    {"category": "Логистика и транспорт", "slug": "transport"},
    {"category": "Сельское хозяйство", "slug": "agro"},
    {"category": "Банки", "slug": "finance"},
    {"category": "Финансовые рынки", "slug": "markets"},
    {"name": "Налоги", "slug": "taxes"},
    {"category": "Регулирование", "slug": "rules"},
    {"category": "Технологии", "slug": "technology"},
    {"category": "Недвижимость", "slug": "realty"},
    {"category": "Международная экономика", "slug": "world"},
]

STARTER_SOURCES: List[str] = [
    "Банк России",
    "Currents API",
    "NewsData.io",
    "Ведомости RSS",
    "MOEX ISS",
    "Аналитика Альфа-Банка",
]
