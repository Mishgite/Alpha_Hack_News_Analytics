# Запуск проекта через Docker Compose

Compose-файлы и Docker-инструкции собраны в `docker/`. Команды запускаются из корня репозитория.

## Полный локальный стек без платного AI

Требуется Docker Engine с Compose v2. Подготовьте локальные настройки и поднимите базу, API и frontend:

```bash
[ -f docker/.env ] || cp docker/.env.example docker/.env
docker compose --env-file docker/.env -f docker/compose.yaml up --build -d
```

Если запускаете из PowerShell: `if (-not (Test-Path docker/.env)) { Copy-Item docker/.env.example docker/.env }`. Не перезаписывайте уже существующий `.env`.

Откройте:

- приложение: <http://127.0.0.1:5173>
- проверка API: <http://127.0.0.1:8000/health>
- Swagger: <http://127.0.0.1:8000/docs>

Проверьте здоровье и логи контейнеров:

```bash
docker compose --env-file docker/.env -f docker/compose.yaml ps
docker compose --env-file docker/.env -f docker/compose.yaml logs init-db api frontend
```

PostgreSQL сохраняет данные в `postgres-data` и доступен с хоста на `localhost:5433` по умолчанию. API и frontend доступны на `8000` и `5173`. Порты можно изменить в `docker/.env`; если меняется порт frontend, обновите `API_CORS_ORIGINS` там же.

## Сквозная проверка на синтетических данных

После запуска стека создайте демокомпанию и три новости, затем откройте интерфейс:

```bash
docker compose --env-file docker/.env -f docker/compose.yaml exec api python -m app.demo_data
```

В интерфейсе выберите компанию `demo-api-company` и должность. В Swagger можно выполнить `POST /api/auth/demo` с телом `{"company_id":"demo-api-company","job_role":"cfo"}`, затем с полученным токеном вызвать `POST /api/feed`.

Это проверяет БД, API, демовход и ленту без обращения к LLM. Для AI-разбора требуется worker и настроенный ключ.

## Worker и бюджет LLM

Worker по умолчанию выключен. Внесите действующий `LLM_API_KEY` в локальный `docker/.env` и проверьте лимиты/остаток бюджета команды. Затем включите профиль:

```bash
docker compose --env-file docker/.env --profile worker -f docker/compose.yaml up --build -d worker
```

Worker опрашивает источники и обрабатывает задания; он может расходовать бюджет без нажатий в UI. Не включайте этот профиль без разрешённого ключа и согласованного лимита.

## Импорт PDF/CSV

Положите файлы в `backend/app/newspaper_parser/data` и запустите одноразовый сервис:

```bash
docker compose --env-file docker/.env --profile ingest -f docker/compose.yaml run --build --rm parser
```

По умолчанию парсер удаляет исходники после успешной записи всех документов. Чтобы сохранить их, добавьте команду парсера и `--keep-files`:

```bash
docker compose --env-file docker/.env --profile ingest -f docker/compose.yaml run --build --rm parser python -m app.newspaper_parser.newspaper_parser --keep-files
```

Backend-образ включает PyMuPDF и Tesseract с русским/английским языками. `openpyxl` в образ не входит — для XLSX его нужно добавить в зависимости образа.

## Остановка и данные

```bash
docker compose --env-file docker/.env -f docker/compose.yaml down
```

Остановка сохраняет volume БД. **`down -v` безвозвратно удалит контейнерную базу и её данные.** Значения из `.env.example` предназначены только для локальной разработки; не используйте их в production.
