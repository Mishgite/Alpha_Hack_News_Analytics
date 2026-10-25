# Сервисы

API вызывает методы сервисов, сервисы работают с БД через репозитории

- Все методы синхронные; из `async def` их нужно вызывать через `asyncio.to_thread`
- Сервис сам открывает сессию и сохраняет изменения; вручную вызывать `commit()` не нужно
- Результаты являются Pydantic-моделями и доступны после закрытия сессии
- `user_id` берётся из результата `authenticate()`, а не из тела запроса клиента
- ID имеют тип `UUID`, кроме `company_id` и ID тегов, у которых тип `str`
- В сигнатурах параметры после `*` передаются по имени; значения после `=` используются по умолчанию

## ProfileService: пользователи и компании

```python
from app.services import ProfileService
from app.schemas.services import Registration, UserSettings, Interests, ProfilePolicy
from app.schemas.database import CompanyData, CompanyTagInput
```

Создание: `ProfileService()` или `ProfileService(policy=...)`
`policy: ProfilePolicy` задаёт веса тем по должностям и влияние реакций; при изменении настроек одна и та же политика передаётся в `FeedService`

### `list_companies(*, limit: int = 50, offset: int = 0) -> list[CompanyData]`

Возвращает компании для выбора, по возрастанию ID

- `limit`: количество компаний, от 1 до 100
- `offset`: сколько записей пропустить, от 0

### `register_demo(data: Registration, *, session_hours: int = 24) -> SessionGrant`

Создаёт пользователя и сессию; каждый вызов создаёт нового пользователя

- `data`: `company_id` существующей компании, `city`, `job_role="other"`
- `job_role`: `ceo`, `cfo`, `accountant`, `treasury`, `employee` или `other`
- `session_hours`: срок сессии в часах, от 1 до 720
- Результат: `user`, `token`, `expires_at`; строка токена доступна через `token.get_secret_value()`

### `authenticate(token: str) -> UserData`

Возвращает пользователя по токену сессии: `id`, `company_id`, `city`, `job_role`, `access_role`
Недействующий или просроченный токен вызывает `PermissionError`

### `logout(token: str) -> None`

Закрывает сессию по токену; повторный вызов ничего не меняет

### `get_profile(user_id: UUID) -> ProfileInputs`

Возвращает пользователя, компанию, корпоративные темы, личные и отключённые теги, счётчики реакций по тегам

### `switch_company(user_id: UUID, company_id: str) -> ProfileInputs`

Выбирает существующую компанию и возвращает обновлённый профиль
Личные интересы сохраняются; ленты прежней компании становятся недоступны

### `update_settings(user_id: UUID, settings: UserSettings) -> UserData`

Изменяет настройки пользователя и возвращает обновлённые данные

- `settings`: обязательные `city` и `job_role`
- Права доступа этим методом не меняются

### `set_interests(user_id: UUID, settings: Interests) -> ProfileInputs`

Полностью заменяет настройки интересов и возвращает обновлённый профиль

- `settings.personal: list[str]`: ID выбранных тегов
- `settings.disabled: list[str]`: ID отключённых тегов
- Оба списка обязательны, могут быть пустыми и не должны пересекаться
- Теги должны существовать и быть активными

### `get_ranking_profile(user_id: UUID) -> RankingProfile`

Возвращает профиль для ранжировщика: веса тем, отрасль, географию, интересующие факторы и версию профиля

### `create_companies(companies: list[CompanyData]) -> list[str]`

Добавляет компании одной транзакцией, существующие ID пропускает без изменения профиля

- `companies`: до 500 моделей `CompanyData`, ID внутри списка должны быть уникальны
- Результат: ID только добавленных компаний; пустой список на входе возвращает пустой список
- При ошибке записи откатывается вся переданная порция

Скрипт импорта вызывает этот метод порциями по 100: [запуск импорта](import-companies.md)

### `save_company(company: CompanyData) -> CompanyData`

Для загрузки компаний из датасета: создаёт компанию или полностью заменяет её профиль

- `company`: обязательные `id` и `profile_version`, остальные поля описаны в [CompanyData](../app/schemas/database.py)
- Неуказанные поля принимают значения по умолчанию, прежние значения не сохраняются
- Результат: сохранённая компания

### `set_company_tags(company_id: str, tags: list[CompanyTagInput]) -> None`

Для загрузки корпоративных интересов: полностью заменяет темы компании

- `tags`: элементы с `tag_id`, `origin` (`rule` или `manual`), `base_weight` от 0 до 2
- Теги должны существовать и быть активными; пары `tag_id` и `origin` не повторяются
- Пустой список удаляет корпоративные темы; личные интересы пользователей сохраняются

## NewsService: новости и признаки

```python
from app.services import NewsService
from app.schemas.services import IncomingNews
from app.schemas.news import NewsFeatures, NewsTag, Geography
```

Создание: `NewsService()`

### `list_tags() -> list[TagData]`

Возвращает активные теги: `id` и `display_name`

### `get_news(news_id: UUID) -> StoredNews`

Возвращает новость: `news_id`, `title`, `text`, `published_at`, `source_url`, `content_hash`, `tagging_status`, `tagging_version`, `features`

Следующие методы предназначены для загрузки и разметки новостей

### `register_source(code: str, *, kind: str) -> None`

Добавляет источник, если его ещё нет
`code` задаёт код источника, `kind` его тип; обе строки обязательны и непустые
Существующий источник не обновляет

### `register_tag(tag_id: str, *, display_name: str) -> None`

Добавляет тег, если его ещё нет
`tag_id` задаёт ID тега, `display_name` отображаемое название; обе строки непустые
Существующий тег не обновляет

### `save_news(article: IncomingNews) -> StoredNews`

Сохраняет новость или обновляет ранее загруженную запись того же источника

- `article.source`: код зарегистрированного активного источника
- `article.title`, `article.body`: заголовок и текст
- `article.published_at`: дата публикации с часовым поясом
- `article.external_id` или `article.url`: нужен хотя бы один идентификатор; URL должен быть HTTP(S)
- `article.language`: язык, по умолчанию `"ru"`
- Результат: сохранённая новость; изменение текста или даты сбрасывает её разметку

### `list_pending_news(*, limit: int = 50) -> list[StoredNews]`

Возвращает новости без разметки, начиная с загруженных раньше
`limit` от 1 до 500; метод только читает список, не закрепляет новости за обработчиком

### `save_features(features: NewsFeatures, *, version: str, expected_content_hash: str, expected_published_at: datetime | None = None) -> StoredNews`

Сохраняет признаки новости и устанавливает статус разметки `ready`

- `features`: обязательные `news_id`, `tags`, `geography`; дополнительные поля в [NewsFeatures](../app/schemas/news.py)
- `tags`: список `NewsTag(id=..., confidence=...)`, уверенность от 0 до 1; теги активные, без повторов
- `geography`: `Geography` с полями `country_code`, `region_codes`, `nationwide`; неизвестные значения можно не задавать
- `version`: непустая версия разметчика
- `expected_content_hash`: `content_hash` новости, взятой для разметки; при несовпадении сохранение отклоняется
- Результат: новость с сохранёнными признаками

## FeedService: персональная лента

```python
from app.services import FeedService
from app.schemas.ranking import RankingRequest, RankingResult
```

Создание: `FeedService(ranker=...)`

- `ranker`: функция, принимающая `RankingRequest` и возвращающая `RankingResult`; сюда подключается выбранная модель ранжирования
- `ranking_config_version="v1"`: версия настроек ранжирования
- `feature_schema_version="v1"`: версия схемы признаков
- `policy=None`: настройки `ProfilePolicy`, как в `ProfileService`
- Без `ranker` доступен только `get_page()`; сам алгоритм ранжирования в сервисе не реализован

### `create_feed(user_id: UUID, *, days: int = 7, candidate_limit: int = 500, page_size: int = 20, ttl_minutes: int = 30) -> SnapshotPage`

Ранжирует новости, сохраняет их порядок в снимке ленты и возвращает первую страницу

- `days`: глубина выборки в днях, от 1 до 365
- `candidate_limit`: максимум новостей для ранжировщика, от 1 до 5000
- `page_size`: размер первой страницы, от 1 до 100
- `ttl_minutes`: срок действия снимка в минутах, от 1 до 1440
- Результат: `snapshot_id`, `items`, `next_position`, `has_more`

### `get_page(user_id: UUID, snapshot_id: UUID, *, position: int = 0, limit: int = 20) -> SnapshotPage`

Возвращает страницу ранее созданной ленты с сохранённым порядком новостей

- `snapshot_id`: ID из результата `create_feed()`
- `position`: начальная позиция от 0; для следующей страницы используется `next_position`, если `has_more=True`
- `limit`: размер страницы, от 1 до 100
- Результат: те же поля, что у `create_feed()`; элементы `items` содержат новость и результат ранжирования
- Снимок должен принадлежать пользователю и текущей компании, срок его действия не должен истечь

## FeedbackService: реакции, показы и открытия

```python
from app.services import FeedbackService
```

Создание: `FeedbackService()`
Методы проверяют доступ к снимку ленты и наличие в нём новости

### `set_reaction(user_id: UUID, news_id: UUID, reaction: Reaction, *, snapshot_id: UUID) -> ReactionCounts`

Сохраняет реакцию пользователя; повтор той же реакции не меняет счётчики

- `reaction`: строка `"like"`, `"dislike"` или `"none"` для снятия реакции
- `snapshot_id`: ID снимка, из которого показана новость
- Результат: `news_id`, `likes_cnt`, `dislikes_cnt`

### `record_impression(*, event_id: UUID, user_id: UUID, snapshot_id: UUID, news_id: UUID, occurred_at: datetime) -> InteractionData`

Записывает один показ новости на пользователя и снимок, повтор с другим `event_id` возвращает уже сохранённое событие

- `event_id`: новый UUID для каждого показа; при повторной отправке того же события ID сохраняется
- `snapshot_id`: ID снимка с новостью
- `occurred_at`: время показа с часовым поясом, не позднее текущего
- Результат: сохранённое событие с ID, временем и типом `impression`; при повторе возвращаются данные первой записи

### `record_open(*, event_id: UUID, user_id: UUID, snapshot_id: UUID, news_id: UUID, occurred_at: datetime) -> InteractionData`

Записывает первое открытие текста новости из снимка. Параметры и защита от повторов такие же, как у `record_impression`; тип события `open`. Метод вызывается отдельно после отображения новости, а не при любом чтении записи из БД. Показ и открытие имеют разные `event_id`.

## InsightService: AI-разборы и вопросы

```python
from app.services import InsightService
from app.schemas.services import AnalysisVersions, AnalysisWork
from app.schemas.insights import InsightResult, SourceReference
```

Создание: `InsightService()`

### `request_analysis(user_id: UUID, news_id: UUID, *, idempotency_key: str) -> JobData`

Создаёт задание на разбор новости для текущей компании пользователя

- `idempotency_key`: непустой ключ запроса; повтор с тем же ключом и параметрами возвращает прежнее задание
- Результат: задание, включая `id`, `status`, `analysis_id`, `error_code`
- Сам AI этим методом не вызывается

### `get_job(user_id: UUID, job_id: UUID) -> JobData`

Возвращает состояние задания по ID из `request_analysis()`
Проверяет владельца и текущую компанию пользователя

### `get_analysis(user_id: UUID, analysis_id: UUID) -> AnalysisData`

Возвращает сохранённый разбор: `id`, `result: InsightResult`, `status` и метаданные
`analysis_id` берётся из завершённого задания; доступ проверяется по текущей компании

### `get_history(user_id: UUID, analysis_id: UUID, conversation_id: UUID, *, limit: int = 5) -> list[QuestionData]`

Возвращает последние вопросы и ответы пользователя в указанном диалоге, от старых к новым

- `analysis_id`: ID разбора
- `conversation_id`: UUID диалога, один и тот же для всех его сообщений
- `limit`: число сообщений, от 1 до 100

### `save_answer(user_id: UUID, analysis_id: UUID, conversation_id: UUID, *, question: str, answer: str, sources: list[SourceReference]) -> QuestionData`

Сохраняет вопрос и уже подготовленный ответ; генерацию ответа выполняет AI-компонент

- `analysis_id`, `conversation_id`: ID разбора и диалога
- `question`: непустой вопрос, до 1000 символов
- `answer`: непустой текст ответа
- `sources`: источники с уникальными `id`; пустой список допустим для ответа об отсутствии данных; поля в [SourceReference](../app/schemas/insights.py)
- Результат: запись вопроса и ответа с ID, источниками и датой создания

### Методы для обработчика AI-заданий

### `claim_job(worker_id: str, *, lease_seconds: int = 120, max_attempts: int = 3) -> JobData | None`

Берёт доступное задание и закрепляет его за обработчиком на ограниченное время

- `worker_id`: непустой идентификатор обработчика
- `lease_seconds`: срок обработки в секундах, от 1
- `max_attempts`: максимум попыток обработки, от 1
- Результат: задание с `id`, `attempts`, `lease_until` или `None`, если заданий нет

### `prepare_job(job_id: UUID, worker_id: str, attempt: int, *, versions: AnalysisVersions) -> AnalysisWork`

Собирает данные для AI-разбора

- `job_id`, `worker_id`: полученное задание и его обработчик
- `attempt`: значение `attempts` из `claim_job()`
- `versions`: обязательные строки `model_id`, `prompt_version`, `report_corpus_version`, `agent_version`, `retrieval_version`
- Результат: `job`, `news`, `context`, `versions`, `cache_key`

### `get_cached_result(work: AnalysisWork) -> AnalysisData | None`

Ищет готовый разбор с актуальным сроком кеша по данным из `prepare_job()`
Возвращает разбор или `None`; само задание не завершает

### `complete_job(work: AnalysisWork, result: InsightResult, *, status: Literal["ready", "partial"] = "ready", ttl_hours: int = 24, trace: list[dict[str, JsonValue]] | None = None) -> AnalysisData`

Сохраняет разбор и завершает задание

- `work`: результат `prepare_job()`
- `result`: подготовленный AI-разбор; поля в [InsightResult](../app/schemas/insights.py)
- `status`: полный (`ready`) или частичный (`partial`) разбор
- `ttl_hours`: срок кеша в часах, от 1 до 720
- `trace`: необязательный список шагов агента в виде JSON-совместимых словарей
- Результат: сохранённый разбор

### `fail_job(job_id: UUID, worker_id: str, attempt: int, *, error_code: str) -> JobData`

Помечает задание как `failed` и возвращает его обновлённое состояние
`attempt` берётся из `claim_job()`, `error_code` является непустым кодом ошибки
Автоматическую новую попытку не создаёт

`prepare_job()`, `get_cached_result()`, `complete_job()` и `fail_job()` требуют действующей попытки обработки, закреплённой за указанным обработчиком

### `search_reports(query: str, *, limit: int = 5) -> list[ReportChunkData]`

Находит фрагменты готовых отчётов для RAG через русский полнотекстовый поиск

- `query`: непустой поисковый запрос
- `limit`: число фрагментов, от 1 до 50
- Результат: текст фрагментов, страницы и метаданные исходных отчётов

## Ошибки и модели

- `LookupError`: запись не найдена
- `PermissionError`: недействующая сессия или нет доступа
- `ValueError`: неверные параметры, истёкший снимок ленты или данные изменились во время обработки
- `pydantic.ValidationError`: неверные поля входной модели

Полные поля моделей: [входные данные сервисов](../app/schemas/services.py), [результаты из БД](../app/schemas/database.py), [новости](../app/schemas/news.py), [ранжирование](../app/schemas/ranking.py), [AI-разборы](../app/schemas/insights.py)

У всех сервисов есть необязательный параметр конструктора `uow_factory=UnitOfWork` для замены способа открытия транзакций; при обычном использовании он не передаётся

## NewsPipeline: парсер, разметка и сохранение

Импорт: `from app.services import NewsPipeline`

Создание: `NewsPipeline(news_service=None, tagger=None)`; параметры позволяют передать готовый `NewsService` и `NewsTagger`

### `save_parsed_news(items, *, source_kind: str) -> ProcessingResult`

- `items`: результаты парсера `NewsItem`; метод `to_incoming_news()` преобразует их в `IncomingNews`
- `source_kind`: тип источника, например `rss` или `api`
- Источники регистрируются при первом появлении; отключённые источники не включаются обратно
- Некорректная новость не прерывает обработку остальных
- Результат: `news_ids` сохранённых новостей и `errors` с позицией элемента и кодом ошибки

### `tag_pending_news(*, limit: int = 50) -> ProcessingResult`

- `limit`: размер порции, от 1 до 500
- Получает новости без разметки, вызывает LLM, сохраняет `NewsFeatures` с проверкой исходных текста и даты
- Некорректный результат модели получает статус `failed`; новая версия текста или даты снова попадает в очередь
- При сетевой ошибке, недоступном провайдере или исчерпанном лимите текущая новость остаётся в очереди, обработка порции прекращается
- Результат: `news_ids` размеченных новостей и `errors` с ID и кодом ошибки
- Перед первым запуском требуется синхронизация справочника через `NewsService.sync_tag_catalog()` или обычный запуск `init_db.py`
- Порции запускаются одним обработчиком; метод не распределяет новости между несколькими одновременно работающими обработчиками

Дополнительные методы `NewsService`:

- `sync_tag_catalog(*, catalog_path=None) -> int`: загружает темы из группы `business` в БД и возвращает их количество; не удаляет существующие темы и не включает отключённые
- `mark_tagging_failed(news: StoredNews) -> bool`: отмечает ошибку для неизменившейся версии новости; используется процессом разметки
- `retry_tagging(news_id: UUID) -> StoredNews`: возвращает `failed`-новость в очередь для явной повторной попытки
- `save_features()` дополнительно принимает `expected_published_at: datetime | None = None`; `NewsPipeline` всегда передаёт исходную дату

## ProfilePipeline: разметка профилей

Импорт: `from app.services import ProfilePipeline`

Создание: `ProfilePipeline(profile_service=None, tagger=None)`; зависимости по умолчанию `ProfileService` и `ProfileTagger`

### `tag_company(company_id: str, *, base_weight: float = 1.0) -> ProfileTags`

Берёт известные признаки компании из БД и сохраняет предложенные темы

- `company_id`: ID существующей компании
- `base_weight`: вес каждой автоматической темы от 0 до 2, отдельная настройка, не уверенность модели
- Сохраняет темы с `origin="rule"`, ручные темы остаются
- Изменившиеся за время запроса данные компании вызывают ошибку вместо сохранения устаревшего результата
- Географию компании из датасета не перезаписывает

### `suggest_interests(user_id: UUID) -> ProfileTags`

Возвращает предложения по деятельности компании и должности пользователя. Личные и отключённые темы не меняет; выбранные пользователем темы сохраняются через `ProfileService.set_interests()`

Дополнительные методы `ProfileService`:

- `get_company(company_id: str) -> CompanyData`: получить компанию для разметки
- `save_company_tagging(expected: CompanyData, tags: list[CompanyTagInput]) -> None`: сохранить автоматические темы при неизменившемся профиле, сохранив ручные

Схемы результатов находятся в `app.schemas.tagging`, описание разметчиков: [LLM](../app/services/ai_agents/readme.md)

## ReportService: отчёты и источники

Импорт: `from app.services.reports import ReportService`

- `save_report(report: ReportInput) -> UUID`: сохранить документ и фрагменты одной транзакцией; повтор версии сохраняет прежние ID
- `import_directory(directory: Path) -> dict`: импортировать подготовленные `*/manifest.json` и страницы; результат содержит `imported`, `skipped`, `errors`
- `get_chunk(chunk_id: UUID) -> ReportChunkData`: получить текст, страницу, сведения OCR и метаданные документа; неизвестный ID вызывает `LookupError`
- `corpus_version() -> str`: получить хэш готового корпуса для кеша агента

Входные схемы: `from app.schemas.reports import ReportInput, ReportPart`. Исходные PDF сервис не распознаёт и не удаляет. Поиск по корпусу: `InsightService.search_reports(query, limit=5)`.

## MarketService: биржа

Импорт: `from app.services.market import MarketService`

- `refresh() -> int`: загрузить MOEX вне транзакции, сохранить срез и вернуть число котировок; вызывается воркером
- `get_overview(*, limit=20) -> MarketOverview`: получить сохранённую карту и лидеров изменения; `limit` от 1 до 100; сетевого запроса не делает

Поля ответа описаны в `app.schemas.market`. Пустая БД возвращает `empty`, старые данные или ошибка обновления дают `stale`.

## QuestionService: уточнения по разбору

Импорт: `from app.services.questions import QuestionService`

- `await ask(user_id, analysis_id, conversation_id, question) -> QuestionData`: проверить доступ, получить ответ агента, проверить цитаты и сохранить вопрос с ответом
- `user_id`, `analysis_id`, `conversation_id`: UUID
- `question`: от 1 до 1000 символов
- Одновременно допускается один запрос пользователя; сразу после завершения действует пауза 10 секунд
- История: последние пять сообщений той же беседы; источники: сохранённый разбор
- При смене компании во время обработки ответ не сохраняется; при ошибке проверки модели возвращается `RuntimeError`

## AnalysisAgent: создание разбора

Импорт: `from app.services.ai_agents.analysis import AnalysisAgent`

- `await get_versions() -> AnalysisVersions`: версии модели, промпта, корпуса и поиска
- `await analyze(work: AnalysisWork) -> AnalysisOutput`: план, поиск, генерация, проверка и одна возможная коррекция; результат содержит `result`, `status`, `trace`
- `await answer(analysis: AnalysisData, history: list[QuestionData], question: str)`: текст ответа и список источников; в API использовать через `QuestionService.ask`

Воркер получает `AnalysisWork` через `InsightService.prepare_job` и завершает задание через `complete_job`. Модель возвращает компактный `AnalysisDraft` с выбранными `evidence_ids`; ID, метаданные источников и дословные цитаты добавляет сервер. Схема публичного результата остаётся `InsightResult`. Лимиты модели и запуск описаны в [инструкции воркера](worker.md).

## Дополнительные методы

- `ProfileService.list_companies(limit=50, offset=0, query="")`: поиск по ID, отрасли, городу и региону
- `ProfileService.get_context(user_id)`: сохранённый снимок фактов о выбранной компании
- `InsightService.get_analysis_context(user_id: UUID, analysis_id: UUID) -> ContextData`: признаки компании на момент сохранённого разбора; импорт `from app.services import InsightService`; не подменяет их текущим профилем, чужая компания вызывает `PermissionError`
- `ProfileService.pending_tagging(version, limit=2)`: компании пользователей, требующие разметки
- `FeedbackService.report_tags(user_id, news_id, *, snapshot_id, wrong_tag_ids, suggested_tag_ids)`: сообщение об ошибке тематических меток с проверкой доступности снимка
- `RuntimeService.get(key)`: последнее состояние фонового процесса; импорт `from app.services.runtime import RuntimeService`

Ключи состояний для чтения: `worker`, `market`, `llm_budget`. Запись служебных состояний выполняется воркером и клиентами LLM.
