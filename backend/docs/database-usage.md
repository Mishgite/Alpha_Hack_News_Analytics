# Репозитории БД

Для API используются [сервисы](services.md). Репозитории нужны при разработке самих сервисов.

## Транзакция

```python
from app.infrastructure.database.uow import UnitOfWork
from app.schemas.database import CompanyData

with UnitOfWork() as db:
    company = db.companies.save(CompanyData(id="company-001", profile_version="v1"))
    db.commit()

# результат доступен и после закрытия сессии
print(company.model_dump(mode="json"))
```

- `commit()` сохраняет изменения всех репозиториев в блоке
- Без `commit()` записи откатываются при выходе из `with`, чтению он не нужен
- `rollback()` отменяет ещё не сохранённые изменения
- Один `UnitOfWork` используется только в одном потоке и одном запросе
- Результаты методов содержат данные, ORM-объекты наружу не возвращаются
- LLM и ранжирование вызываются после закрытия сессии

Подключение берётся из `backend/app/.env`. [Настройка БД](database-setup.md).

## Методы

Вызовы ниже выполняются внутри `with UnitOfWork() as db`. После `*` параметры передаются по имени. Даты содержат часовой пояс, ID записей имеют тип `UUID`.

### Компании: `db.companies`

- `get(company_id)`: `CompanyData | None`

  Читает компанию по строковому ID.

- `list(*, limit=50, offset=0)`: `list[CompanyData]`

  Компании по ID; `limit` от 1 до 100, `offset >= 0`.

- `save(company)`: `CompanyData`

  Создаёт компанию или заменяет все поля из CompanyData, включая значения по умолчанию.

- `set_tags(company_id, tags)`: `None`

  Заменяет корпоративные темы списком `CompanyTagInput`, проверяет активные ID и уникальность пары ID/origin.

- `get_context_evidence(company_id)`: `dict`

  Возвращает источники признаков, связи и темы; перед вызовом нужна блокировка компании.

- `save_context(company_id, payload, versions)`: `ContextData`

  Сохраняет снимок данных и версий источников; одинаковые данные возвращают прежний снимок.

### Пользователи: `db.users`

- `get(user_id)`: `UserData`

  Читает пользователя; если его нет, возникает `LookupError`.

- `update_settings(user_id, *, city, job_role)`: `UserData`

  Меняет город и должность под блокировкой пользователя.

- `revoke_session(raw_token)`: `None`

  Отзывает сессию по хэшу токена.

- `create(*, company_id, city, job_role="other")`: `UserData`

  Создаёт пользователя у существующей компании, `access_role="user"`.

- `switch_company(user_id, company_id)`: `UserData`

  Меняет выбранную компанию на существующую.

- `set_interests(user_id, *, personal, disabled)`: `None`

  Полностью заменяет личные и отключённые теги списками строковых ID.

- `get_profile_inputs(user_id)`: `ProfileInputs`

  Собирает данные для расчёта весов, блокируя пользователя и компанию до конца транзакции.

- `get_ranking_profile(user_id, *, tag_weights, profile_version)`: `RankingProfile`

  Собирает профиль с **готовыми** весами `dict[str, float]` в диапазоне `[0, 2]`.

- `create_session(user_id, raw_token, expires_at)`: `SessionData`

  Сохраняет хэш токена длиной от 32 символов.

- `resolve_session(raw_token)`: `UserData | None`

  Ищет пользователя по действующему, не отозванному токену.

### Новости: `db.news`

- `register_source(code, *, kind)`: `None`

  Регистрирует источник; существующий код не обновляет.

- `register_tag(tag_id, *, display_name)`: `None`

  Регистрирует тег; существующий ID не обновляет.

- `save_news(*, source, external_id, url, title, body, published_at, language="ru")`: `StoredNews`

  Создаёт или обновляет новость по external_id или URL внутри источника; изменение текста или даты сбрасывает разметку.

- `get(news_id, *, lock=False)`: `StoredNews`

  Возвращает StoredNews; lock=True удерживает блокировку до конца транзакции.

- `list_tags()`: `list[TagData]`

  Активные теги по ID: `id`, `display_name`.

- `list_pending_news(*, limit=50)`: `list[StoredNews]`

  Неразмеченные новости по времени загрузки, `limit` от 1 до 500.

- `check_candidates(expected)`: `None`

  Принимает `list[NewsCandidate]`; проверяет актуальность дат, признаков и весов качества, блокирует новости до сохранения ленты.

- `get_for_tagging(news_id)`: `NewsForTagging`

  Возвращает ID, заголовок, текст, дату и URL без служебных полей.

- `save_features(features, *, version, expected_content_hash)`: `StoredNews`

  Заменяет разметку и ставит ready, если expected_content_hash совпадает с текущим текстом.

- `list_candidates(*, since, as_of, limit=500)`: `list[NewsCandidate]`

  Выбирает новости `ready` с датой публикации в `[since, as_of]` и загрузкой не позднее `as_of`.

### Лента: `db.feeds`

- `save(*, profile, result, context_id, expires_at, candidate_cutoff_at, feature_schema_version, config_hash)`: `SnapshotData`

  Сохраняет `RankingProfile`, готовый `RankingResult` и снимок отображаемых полей новостей.

- `get_for_user(user_id, snapshot_id)`: `SnapshotData`

  Проверяет владельца, выбранную компанию и срок действия снимка.

- `get_page(user_id, snapshot_id, *, position=0, limit=20)`: `SnapshotPage`

  Возвращает страницу после тех же проверок доступа; позиции с 0, `limit`: от 1 до 100.

### Реакции и просмотры: `db.feedback`

- `set_reaction(user_id, news_id, reaction, *, snapshot_id=None)`: `ReactionCounts`

  Устанавливает `like`, `dislike` или снимает реакцию через `none`. При `snapshot_id=None` принадлежность ленте не проверяется.

- `record_impression(*, event_id, user_id, snapshot_id, news_id, occurred_at)`: `InteractionData`

  Записывает показ новости из доступного снимка.

### AI-разборы и задания: `db.analyses`

- `get_for_user(user_id, analysis_id)`: `AnalysisData`

  Читает разбор с проверкой выбранной компании.

- `get_cached_result(user_id, cache_key)`: `AnalysisData | None`

  Проверяет компанию, срок кеша и хэш текста; статус ready проверяет сервис.

- `save(user_id, data)`: `AnalysisData`

  Принимает AnalysisWrite; возвращает действующий ready или создаёт новую запись, сохраняя прежнюю вместе с вопросами.

- `get_job(job_id)`: `JobData`

  Читает задание для worker без проверки прав пользователя.

- `get_job_for_user(user_id, job_id)`: `JobData`

  Чтение задания с проверкой владельца и выбранной компании.

- `add_question(user_id, analysis_id, conversation_id, question, answer, sources)`: `QuestionData`

  Сохраняет готовые вопрос, ответ и JSON-совместимый список источников после проверки доступа.

- `get_history(user_id, analysis_id, conversation_id, *, limit=5)`: `list[QuestionData]`

  Последние сообщения конкретного пользователя и диалога в порядке от старых к новым; `limit`: от 1 до 100.

- `create_job(user_id, news_id, *, idempotency_key)`: `JobData`

  Создаёт задание; повтор ключа для того же пользователя и запроса возвращает прежнее.

- `claim_job(worker_id, *, lease_seconds=120, max_attempts=3)`: `JobData | None`

  Выдаёт задание worker, увеличивает номер попытки; требует commit() даже при None.

- `finish_job(job_id, worker_id, attempt, *, analysis_id=None, error_code=None)`: `JobData`

  Завершает текущую попытку с analysis_id или error_code; проверяет worker, номер попытки и срок.

### Отчёты: `db.reports`

- `search(query, *, limit=5)`: `list[ReportChunkData]`

  Полнотекстовый поиск по русским словоформам в чанках отчётов со статусом `ready`, по релевантности.

## Схемы Pydantic

- [database.py](../app/schemas/database.py): компании, пользователи, ленты, задания, сохранённые разборы
- [news.py](../app/schemas/news.py): текст и признаки новости
- [ranking.py](../app/schemas/ranking.py): вход и результат ранжировщика
- [insights.py](../app/schemas/insights.py): ответ AI и источники

`AnalysisData.result` содержит ответ, `AnalysisData.trace` содержит шаги агента. Для записи используется `AnalysisWrite.agent_trace_json`.

## Ошибки

- `LookupError`: запись не найдена, если метод не предусматривает None
- `PermissionError`: чужие данные или другая выбранная компания
- `ValueError`: неверные параметры, устаревшие данные или истёкший срок обработки
- `IntegrityError`: нарушено ограничение PostgreSQL
- `OperationalError`: ошибка подключения

Обработка исключений располагается снаружи `with`, после отката транзакции.
