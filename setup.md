# Установка, запуск и тестирование

[Обзор проекта](readme.md) · [API](readme.md#api) · [PyCharm](#запуск-в-pycharm) · [PostgreSQL](#5-postgresql)

## Выбрать режим

| Режим | Что нужно | Что работает |
|---|---|---|
| **Интерфейс** | Node.js | Экраны и сценарии на синтетических данных, без серверных запросов |
| **API + БД** | Python, PostgreSQL, Node.js | Профили, теги, сохранённые новости, лента и реакции |
| **Полный** | Всё выше + ключ LLM + worker | Свежие новости, разметка, AI-разборы и уточнения |

Для запуска без локальных зависимостей и своих датасетов: **[Docker с готовыми данными](docker/README.md)**. Следующие разделы описывают также ручной запуск для разработки

## 1. Требования и клонирование

| Инструмент | Версия |
|---|---|
| Python | **3.12** |
| PostgreSQL | **17.x** |
| Node.js | **22.12+**, npm из комплекта |
| Git | Для клонирования |
| Docker + Compose | Если запускаем PostgreSQL в контейнере |

```bash
git clone https://github.com/Mishgite/Alpha_Hack_News_Analytics.git
cd Alpha_Hack_News_Analytics
```

Команды ниже выполняются **из корня репозитория**, если рядом не указана другая папка.

## 2. Быстрый просмотр интерфейса

```bash
cd frontend
npm ci
npm run demo
```

Открыть **http://127.0.0.1:5173**. Выбрать компанию и должность, открыть ленту, изменить темы, посмотреть разбор и биржу. Данные и ответы AI в этом режиме имитируются. Остановка — `Ctrl+C`; перед полным запуском освободить порт 5173.

## 3. Python и зависимости

Linux / macOS:

```bash
python3.12 -m venv backend/app/.venv
source backend/app/.venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3.12 -m venv backend/app/.venv
.\backend\app\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Если PowerShell блокирует активацию, можно выполнять команды через `.\backend\app\.venv\Scripts\python.exe`. Корневой `requirements.txt` подключает закреплённые версии из `backend/app/requirements.txt`.

## 4. Конфигурация

Linux / macOS:

```bash
cp backend/app/.env.example backend/app/.env
cp frontend/.env.example frontend/.env.local
```

Windows PowerShell:

```powershell
Copy-Item backend/app/.env.example backend/app/.env
Copy-Item frontend/.env.example frontend/.env.local
```

Копировать примеры нужно при первом запуске. Существующие `.env` с настройками команды сохраняем.

| Файл / параметр | Значение |
|---|---|
| `backend/app/.env` → `DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/alfa_news` |
| `API_DEMO_ENABLED` | `true` для выбора компании на хакатоне |
| `API_CORS_ORIGINS` | JSON-массив с `http://127.0.0.1:5173` и `http://localhost:5173` |
| `frontend/.env.local` → `VITE_API_URL` | `http://127.0.0.1:8000`, без `/api` |
| `LLM_API_KEY` | Ключ команды; нужен для реальных AI-запросов |
| `LLM_BASE_URL`, `LLM_MODEL_*` | Значения из `.env.example` для шлюза хакатона |
| `LLM_DAILY_REQUEST_LIMIT` | По примеру — `100` попыток за сутки UTC в одной БД |
| `LLM_BUDGET_RESERVE_RUB` | По примеру — остановка новых вызовов при остатке `≤ 50 ₽` |
| `LLM_MAX_OUTPUT_TOKENS` | По примеру — `8192` |

Спецсимволы пароля в URL кодируются: `@` → `%40`, `#` → `%23`. Ключ модели хранится только в backend. После изменения окружения перезапустить соответствующий процесс.

## 5. PostgreSQL

Выбрать один вариант.

### Вариант A — Docker

[Полная инструкция](docker/README.md). Из корня репозитория:

```bash
docker compose -f docker/compose.yaml up --build -d
```

Открыть **http://127.0.0.1:5173**. Compose запускает PostgreSQL, импорт, API, worker и frontend. Автоматически загружаются 50 обезличенных компаний из текущей выборки, 104 реальные новости с признаками и фрагменты девяти отчётов

Установка Python, Node.js и PostgreSQL на хосте, ручной импорт и отдельный запуск процессов из следующих разделов для этого варианта не нужны. Ключ модели требуется только для новых AI-запросов и разметки новых публикаций

### Вариант B — установленный PostgreSQL

Создать БД через pgAdmin или терминал:

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -W -c "CREATE DATABASE alfa_news;"
```

В `DATABASE_URL` указать свой пароль, порт `5432` и базу `alfa_news`. Затем, с активированным Python-окружением:

```bash
python backend/app/infrastructure/database/init_db.py
```

Ожидаем `Reaction trigger: OK` и `OK`. Повторный запуск сохраняет данные и синхронизирует справочник тегов; произвольные изменения существующих таблиц автоматически не мигрируются.

## 6. Данные для старта

### Проверить приложение без ключа модели

```bash
python backend/app/demo_data.py
```

Скрипт создаёт компанию `demo-api-company` и **3 синтетические новости**. Выбрать эту компанию в интерфейсе. Можно проверять API, профиль, ленту и реакции; для AI-разбора нужен реальный LLM и worker.

### Подключить материалы хакатона

| Материал | Путь | Назначение |
|---|---|---|
| `df_Uid_data_hack.csv` | `backend/data/companies/` | Исходные данные компаний |
| `selection.txt` | `backend/data/companies/` | Необязательный список 50 ID, по одному в строке |
| `manifest.json` + JSON страниц | `backend/data/reports_processed/` | Подготовленная аналитика банка |
| Исходные PDF | `backend/data/reports/` | Открытие оригинала цитируемого документа |

CSV и отчёты получить у команды; в Git они не хранятся. Без `selection.txt` импорт сам выбирает 50 компаний и сохраняет их ID.

```bash
python backend/app/import_companies.py --check
python backend/app/import_companies.py
python backend/app/import_news.py
python backend/app/import_reports.py
```

| Команда | Результат | Вызовы LLM |
|---|---|---|
| `import_companies.py --check` | Проверка CSV и выборки без БД | Нет |
| `import_companies.py` | Импорт и разметка 50 профилей; публикация выборки после завершения | Да, для ещё не готовых профилей |
| `import_news.py` | 104 публикации из JSON в репозитории | Нет |
| `import_reports.py` | Подготовленные страницы и фрагменты отчётов в БД | Нет |

Повторный импорт новостей не создаёт дубли. Импорт компаний продолжает обработку готовой выборки и пропускает уже размеченные версии. `--skip-tagging` импортирует компании без модели и без публикации новой выборки интерфейса.

Даты новостей сохраняются исходными: если лента пустая, расширить период через **«Фильтр»**. Без материалов банка разбор новости возможен, но подтверждённой позиции банка в нём может не быть.

### PDF / OCR / XLSX — при необходимости

Для локального чтения PDF и XLSX установить дополнительные зависимости в Python-окружение проекта:

```bash
python -m pip install pymupdf openpyxl
```

Для OCR сканов нужен Tesseract с русским и английским языками. В Docker-образе уже есть PyMuPDF и Tesseract. `import_reports.py` читает готовые JSON; исходные PDF/CSV обрабатывает отдельный [парсер](backend/app/newspaper_parser/newspaper_parser.py).

Чтобы импортировать исходные материалы в Docker, положить их в `backend/app/newspaper_parser/data/` и выполнить:

```bash
docker compose --env-file docker/.env --profile ingest -f docker/compose.yaml run --build --rm parser python -m app.newspaper_parser.newspaper_parser --keep-files
```

`--keep-files` сохраняет входные файлы после импорта. Для XLSX в контейнер также потребуется добавить `openpyxl`.

## 7. Запуск сервисов

Открыть отдельный терминал для каждого процесса. В Python-терминалах активировать окружение из шага 3.

| Терминал | Папка | Команда |
|---|---|---|
| API | Корень проекта | `python backend/app/server.py` |
| Frontend | `frontend/` | `npm ci`, затем `npm run dev` |
| Worker | Корень проекта | `python backend/app/worker.py` |

| Адрес | Что открыть |
|---|---|
| http://127.0.0.1:5173 | Приложение |
| http://127.0.0.1:8000/health | Состояние HTTP-сервера; БД этот маршрут не проверяет |
| http://127.0.0.1:8000/docs | Swagger с API и схемами |

Без worker работают сохранённые данные. Новые AI-разборы требуют worker. Уточняющие вопросы к готовому разбору вызывают модель через API и расходуют бюджет даже без worker.

На одну БД запускается один worker. Для собственных RSS и интервалов:

```bash
python backend/app/worker.py --config /path/to/worker.json
```

Пример `worker.json`:

```json
{
  "sources": [{"code": "cbr", "url": "https://www.cbr.ru/rss/RssPress", "limit": 30, "full_text": false}],
  "fetch_interval": 900,
  "tagging_interval": 300,
  "tagging_batch": 1,
  "profile_interval": 120,
  "profile_batch": 1,
  "analysis_interval": 5,
  "market_interval": 900,
  "market_enabled": true
}
```

Все интервалы — в секундах. `sources: []` отключает RSS, `market_enabled: false` — биржевые запросы.

## 8. Автоматические тесты

### Backend без PostgreSQL и платных LLM-вызовов

С активированным окружением, **из папки `backend`**:

```bash
python -m pytest app/test_backend.py app/test_errors.py app/test_ranking.py app/test_profile_roles.py app/services/ai_agents/test_ai_agents.py -q
```

Проверяются ранжирование, роли и теги, валидация ответов, цитаты, ошибки API, бюджетные ограничения и поведение агентов с тестовыми транспортами. Проверки, которым нужна БД, будут пропущены.

### Backend с PostgreSQL

Настроить `DATABASE_URL` и запустить БД. Из `backend`, Linux / macOS:

```bash
RUN_DATABASE_TESTS=1 RUN_DB_INTEGRATION=1 python -m pytest app/test_backend.py app/test_errors.py app/test_ranking.py app/test_profile_roles.py app/services/ai_agents/test_ai_agents.py -q
```

Windows PowerShell:

```powershell
$env:RUN_DATABASE_TESTS = "1"
$env:RUN_DB_INTEGRATION = "1"
python -m pytest app/test_backend.py app/test_errors.py app/test_ranking.py app/test_profile_roles.py app/services/ai_agents/test_ai_agents.py -q
Remove-Item Env:RUN_DATABASE_TESTS, Env:RUN_DB_INTEGRATION
```

`RUN_DATABASE_TESTS` создаёт временную схему; `RUN_DB_INTEGRATION` — отдельную временную БД. Нужны права `CREATE SCHEMA` и `CREATE DATABASE`; тестовые объекты удаляются после проверки. Эти тесты также подменяют LLM и не используют платный шлюз.

### Frontend

Из `frontend`:

```bash
npm test
npm run build
```

Первая команда проверяет API-клиент, действия, ошибки, источники, события и рынок. Вторая создаёт `frontend/dist`. Для просмотра сборки остановить dev-сервер и выполнить `npm run preview`.

## 9. Проверка перед защитой

| Действие | Ожидаемый результат |
|---|---|
| `python backend/app/infrastructure/database/init_db.py --check` | Таблицы и триггер реакций доступны |
| Открыть `/health` и `/docs` | API отвечает |
| Выбрать компанию и роль | Лента загрузилась |
| При той же роли сменить отрасль компании | Подборка учитывает новую компанию |
| Добавить тему, отключить другую, обновить страницу | Настройки сохранились |
| Поставить и снять реакцию | Реакция сохраняется и корректно отменяется |
| Запустить AI-разбор | Очередь завершается результатом `ready` или `partial` |
| Открыть цитату и задать вопрос | Источник доступен, ответ связан с тем же разбором |
| Открыть биржевой обзор | Видны котировки и время самих цен |

Состояние worker и последний проверенный остаток бюджета: `GET /api/status` с Bearer-токеном сессии. AI-разборы хранятся в локальной БД — перед защитой их нужно подготовить на том компьютере, с которого показывается проект.

## 10. Если что-то не запускается

| Симптом | Что проверить |
|---|---|
| `No module named ...` | Активное окружение и `python -m pip install -r requirements.txt` из корня |
| `No module named app` | Модули `python -m app...` запускаются из `backend`; прямые команды выше — из корня |
| Ошибка соединения с БД | Служба / контейнер, пароль и порт: `5432` локально или `5433` через Compose |
| `npm.ps1` заблокирован | На Windows использовать `npm.cmd ci`, `npm.cmd run dev` |
| Порт 5173 или 8000 занят | Остановить предыдущий процесс |
| Интерфейс не получает данные | `/health`, `VITE_API_URL`, CORS, перезапуск после изменения `.env` |
| Нет компаний | Выполнить `demo_data.py` или полностью завершить `import_companies.py` |
| Пустая лента | Компания, выбранные теги, импорт новостей, период фильтра |
| `Analysis worker unavailable` | Worker запущен, его heartbeat актуален, LLM настроен |
| Модель не отвечает | Ключ, HTTPS-шлюз, разрешённая модель, суточный лимит и остаток бюджета |
| Нет позиции банка / PDF | Импорт отчётов и наличие исходного документа |

## Остановка и обновление

Процессы API, frontend и worker: `Ctrl+C`. БД Docker:

```bash
docker compose --env-file docker/.env -f docker/compose.yaml down
```

Данные остаются в volume. Не добавлять `-v`, если БД нужно сохранить.

После `git pull`: обновить изменившиеся зависимости, сверить `.env.example`, выполнить `init_db.py` и перезапустить сервисы.

## Запуск в PyCharm

1. Открыть корень проекта; выбрать интерпретатор `backend/app/.venv`.
2. Отметить `backend` как **Sources Root**; выбрать установленный Node.js.
3. Подготовить `.env`, БД и данные по шагам выше.
4. Запустить конфигурацию **«Все сервисы»** из `.run` или **«Без воркера»** для проверки без новых разборов.

Отдельные конфигурации: **Backend**, **Frontend**, **Worker**, **Компании - импорт 50**, **БД - создать таблицы**, **БД - проверить**. PostgreSQL запускается отдельно.

## Проверка API через Swagger

1. Выполнить `POST /api/auth/demo`: `{"company_id": "demo-api-company", "job_role": "cfo"}`.
2. Скопировать `access_token`, нажать **Authorize**, вставить токен без слова `Bearer`.
3. Выполнить `POST /api/feed`: `{"days": 7, "page_size": 2}`.
4. Для следующей страницы вызвать `GET /api/feed/{snapshot_id}` с `position`, равным `next_position` из ответа.

Создание разбора принимает `{"idempotency_key": "demo-analysis-1"}`; повтор одного ключа возвращает прежнее задание. Доступные статусы и поля — в Swagger.

## GitHub Pages

1. Разместить API и PostgreSQL на сервере с публичным HTTPS-адресом API.
2. Добавить `https://mishgite.github.io` в серверный `API_CORS_ORIGINS` и перезапустить API.
3. В GitHub **Settings → Secrets and variables → Actions → Variables** задать `VITE_API_URL` без `/api`.
4. В **Settings → Pages → Source** выбрать **GitHub Actions**.
5. Запустить **Actions → Frontend · GitHub Pages → Run workflow**.

Workflow публикует только `frontend/dist`. Значения `VITE_*` доступны браузеру; серверные ключи остаются в backend. Без доступного HTTPS API серверная версия интерфейса на Pages не работает.
