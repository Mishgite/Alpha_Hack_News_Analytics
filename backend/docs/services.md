# Использование сервисов

[Подключение к БД](database-setup.md) · [Репозитории](database-usage.md)

API вызывает сервисы из `app.services`. Они сами сохраняют изменения и закрывают сессию БД. Результат возвращается как Pydantic DTO: для JSON используется `result.model_dump(mode="json")`.

В примерах `user_id` берётся из проверенной сессии. ID записей имеют тип `UUID`, ID компаний и тегов имеют тип `str`. Рабочая папка для Python: `backend`.

## Пользователь и настройки

```python
from app.services import ProfileService
from app.schemas.services import Registration, UserSettings, Interests

profiles = ProfileService()
companies = profiles.list_companies(limit=50, offset=0)
grant = profiles.register_demo(
    Registration(company_id=companies[0].id, city="Москва", job_role="cfo"),
    session_hours=24,
)
token = grant.token.get_secret_value()
user = profiles.authenticate(token)
user_id = user.id
```

Нужна хотя бы одна загруженная компания. `grant` содержит `user`, `token`, `expires_at`. Токен извлекается отдельно: обычный `model_dump()` его скрывает. Повторная регистрация создаёт нового пользователя.

```python
profile = profiles.get_profile(user_id)
user = profiles.update_settings(user_id, UserSettings(city="Казань", job_role="cfo"))
profile = profiles.switch_company(user_id, company_id="company-002")
profile = profiles.set_interests(
    user_id, Interests(personal=["currency"], disabled=["sport"]),
)
ranking_profile = profiles.get_ranking_profile(user_id)
profiles.logout(token)
```

- `get_profile`, `switch_company`, `set_interests`: возвращают `ProfileInputs` с пользователем, компанией, темами и реакциями
- `update_settings`: возвращает `UserData`; `get_ranking_profile`: `RankingProfile` с весами тем
- `set_interests` заменяет оба списка целиком; теги должны существовать, быть активными и не входить сразу в оба списка
- `switch_company` сохраняет личные темы, но закрывает доступ к лентам другой компании
- `job_role`: `ceo`, `cfo`, `accountant`, `treasury`, `employee`, `other`

### Импорт компании

Внутренние методы для загрузчика данных:

```python
from app.schemas.database import CompanyData, CompanyTagInput

company = profiles.save_company(CompanyData(id="company-001", profile_version="v1"))
profiles.set_company_tags(company.id, [
    CompanyTagInput(tag_id="currency", origin="rule", base_weight=1.0),
])
```

`save_company` заменяет профиль целиком. `set_company_tags` заменяет все темы компании, `origin` допускает `rule` или `manual`, вес от 0 до 2. Теги предварительно регистрируются через `NewsService`.

### Настройки весов

```python
from app.schemas.services import ProfilePolicy

policy = ProfilePolicy(role_weights={"cfo": {"currency": 1.0}})
profiles = ProfileService(policy=policy)
```

По умолчанию веса должностей пустые. Одна и та же `policy` передаётся в `ProfileService` и `FeedService`. Вес темы берётся как максимум корпоративного, должностного и личного веса. Реакции корректируют его в пределах от 0 до 2, отключённые темы получают 0. Расчёт находится в [build_profile](../app/services/profiles.py).

## Новости

### Сохранить или обновить

```python
from datetime import UTC, datetime
from app.services import NewsService
from app.schemas.services import IncomingNews

news = NewsService()
news.register_source("example-rss", kind="rss")
news.register_tag("currency", display_name="Валютный рынок")
article = news.save_news(IncomingNews(
    source="example-rss",
    external_id="article-001",
    title="Изменение курса валют",
    body="Текст новости",
    published_at=datetime.now(UTC),
))
```

Возвращает `StoredNews`, включая `news_id` и `content_hash`. Нужен `external_id` или HTTP(S)-адрес `url`. Повторная загрузка обновляет запись того же источника. Изменение текста или даты сбрасывает разметку.

### Прочитать и разметить

```python
article = news.get_news(article.news_id)          # текст и признаки новости
tags = news.list_tags()                          # активные теги
pending = news.list_pending_news(limit=50)        # новости без разметки
```

`list_pending_news` возвращает до 500 новостей без разметки, начиная с загруженных раньше. Метод не закрепляет их за обработчиком.

```python
from app.schemas.news import Geography, NewsFeatures, NewsTag

# здесь пример признаков, в приложении их возвращает разметчик
features = NewsFeatures(
    news_id=article.news_id,
    tags=[NewsTag(id="currency", confidence=0.9)],
    geography=Geography(),
)
ready = news.save_features(
    features, version="tagger-v1", expected_content_hash=article.content_hash,
)
```

Возвращает `StoredNews` со статусом `ready`. Если текст успел измениться, возникает `ValueError`: требуется прочитать и разметить новую версию.

## Лента

### Создать

```python
from app.services import FeedService

# rank_news передаётся из модуля ML: RankingRequest -> RankingResult
feed = FeedService(ranker=rank_news, policy=policy)
page = feed.create_feed(user_id, days=7, candidate_limit=500, page_size=20, ttl_minutes=30)
```

Параметры:

- `days`: за сколько последних дней брать новости, от 1 до 365
- `candidate_limit`: сколько новостей передать ранжировщику, от 1 до 5000
- `page_size`: сколько новостей вернуть на странице, от 1 до 100
- `ttl_minutes`: сколько минут доступна сохранённая лента, от 1 до 1440

Результат `SnapshotPage`: `snapshot_id`, `items`, `has_more`, `next_position`.

### Следующая страница

```python
if page.has_more:
    page = feed.get_page(user_id, page.snapshot_id, position=page.next_position, limit=20)
```

Порядок новостей фиксируется при создании ленты. Для обновления интересов или истёкшей ленты вызывается `create_feed`.

**Для подключения ML:** ранжировщик вызывается без открытой сессии БД. Он должен вернуть уникальные новости из полученных кандидатов. Если профиль или признаки изменились за время расчёта, сервис вызывает `ValueError`, и ленту нужно построить заново. Без `ranker` работает только `get_page`.

## Реакции и показы

```python
from datetime import UTC, datetime
from uuid import uuid4
from app.services import FeedbackService

feedback = FeedbackService()
counts = feedback.set_reaction(user_id, news_id, "like", snapshot_id=snapshot_id)
event = feedback.record_impression(
    event_id=uuid4(), user_id=user_id, snapshot_id=snapshot_id,
    news_id=news_id, occurred_at=datetime.now(UTC),
)
```

- Реакция: `like`, `dislike` или `none` для снятия
- `counts`: `news_id`, `likes_cnt`, `dislikes_cnt`; `event`: `InteractionData`
- Новость должна входить в доступную пользователю ленту
- При повторной отправке показа используется прежний `event_id`, при новом показе создаётся новый
- Повтор той же реакции не увеличивает счётчики

## AI-разбор

### Запрос и получение результата

```python
from uuid import uuid4
from app.services import InsightService

insights = InsightService()
request_key = str(uuid4())
job = insights.request_analysis(user_id, news_id, idempotency_key=request_key)
job = insights.get_job(user_id, job.id)
if job.status == "ready":
    analysis = insights.get_analysis(user_id, job.analysis_id)
    result = analysis.result
```

`request_analysis` и `get_job` возвращают `JobData`. Один запрос при повторной отправке использует прежний ключ. Для нового разбора нужен новый ключ, в том числе после `failed`.

`get_analysis` возвращает `AnalysisData`: ответ в `result`, шаги агента в `trace`. Полнота ответа указана в `analysis.status`: `ready` или `partial`.

### Обработать задание

Внутренние методы для worker. `versions` имеет тип [AnalysisVersions](../app/schemas/services.py): `model_id`, `prompt_version`, `report_corpus_version`, `agent_version`, `retrieval_version`. `agent(work)` в примере возвращает `InsightResult` и список словарей с шагами агента.

```python
def process_one(insights, agent, versions):
    worker_id = "worker-1"
    job = insights.claim_job(worker_id, lease_seconds=300, max_attempts=3)
    if job is None:
        return None
    try:
        work = insights.prepare_job(job.id, worker_id, job.attempts, versions=versions)
        cached = insights.get_cached_result(work)
        if cached is not None:
            result, trace = cached.result, cached.trace
        else:
            result, trace = agent(work)
        return insights.complete_job(work, result, trace=trace)
    except Exception:
        try:
            insights.fail_job(job.id, worker_id, job.attempts, error_code="analysis_failed")
        except ValueError:
            # попытка могла истечь или перейти другому worker
            pass
        raise
```

- `claim_job`: `JobData` или `None`, если заданий нет
- `prepare_job`: `AnalysisWork` с полями `job`, `news`, `context`, `versions`, `cache_key`
- `get_cached_result`: `AnalysisData` или `None`
- `complete_job`: сохраняет ответ и завершает задание, возвращает `AnalysisData`
- `fail_job`: записывает ошибку, возвращает `JobData` со статусом `failed`

У `complete_job` есть параметры `status="ready"`, `ttl_hours=24` и `trace=None`. Для неполного ответа передаётся `status="partial"`. Срок кеша от 1 до 720 часов. Старые разборы и их вопросы сохраняются при пересчёте.

Срок обработки задания не продлевается автоматически. После истечения задание может забрать другой worker. `failed` автоматически не перезапускается. Сам цикл worker и AI-агент пока не реализованы.

### Поиск по отчётам и вопросы

```python
chunks = insights.search_reports("валютный рынок", limit=5)
messages = insights.get_history(user_id, analysis_id, conversation_id, limit=5)
message = insights.save_answer(
    user_id, analysis_id, conversation_id,
    question=question, answer=answer, sources=sources,
)
```

- `search_reports`: `list[ReportChunkData]`, включая текст, страницу, название файла и ссылку; `limit` от 1 до 50
- `get_history`: `list[QuestionData]` данного пользователя и диалога от старых сообщений к новым; `limit` от 1 до 100
- `save_answer`: `QuestionData`; сохраняет уже готовый ответ, AI не вызывает
- `question`: до 1000 символов; `answer` непустой; `sources`: непустой список [SourceReference](../app/schemas/insights.py) с уникальными ID

## Вызов из async API

Методы сервисов синхронные. В `async def` весь вызов выполняется через `asyncio.to_thread`:

```python
import asyncio

async def load_profile(token: str):
    user = await asyncio.to_thread(profiles.authenticate, token)
    profile = await asyncio.to_thread(profiles.get_profile, user.id)
    return profile.model_dump(mode="json")
```

## Ошибки

- `LookupError`: запись не найдена
- `PermissionError`: сессия недействительна или нет доступа к данным
- `ValueError`: неверные параметры, истёкшая лента или попытка обработки, данные изменились
- `pydantic.ValidationError`: входные данные не соответствуют DTO
- Ошибки SQLAlchemy: соединение или ограничения БД

HTTP-коды назначает API. Импорт компаний, регистрация источников и методы worker предназначены для внутреннего кода. Демо-регистрация пока не проверяет принадлежность сотрудника к компании.
