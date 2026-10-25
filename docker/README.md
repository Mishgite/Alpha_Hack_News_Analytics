# Docker для Alpha Hack News Analytics

Все Docker-файлы находятся в этой папке. Сборка использует `../` как контекст, чтобы взять backend-код, но Dockerfile и его ignore-файл остаются здесь.

## Что запускается

- `database` — PostgreSQL 17 с постоянным Docker volume `postgres-data`.
- `init-db` — одноразовый контейнер, создаёт или проверяет 31 таблицу проекта и триггер реакций.
- `parser` — необязательный профиль `ingest`: импортирует PDF/CSV из `backend/app/newspaper_parser/data`.

HTTP-сервис здесь не добавлен: в текущем backend нет точки входа HTTP-сервера, а `frontend/` пуст. Поэтому `docker compose up` поднимает БД и инициализирует схему, но не запускает API или веб-интерфейс.

## Запуск БД

Из корня репозитория:

```bash
cp docker/.env.example docker/.env
docker compose --env-file docker/.env -f docker/compose.yaml up --build -d
```

Проверить контейнеры и результат инициализации:

```bash
docker compose --env-file docker/.env -f docker/compose.yaml ps -a
docker compose --env-file docker/.env -f docker/compose.yaml logs init-db
```

Контейнерная БД доступна с хоста на `localhost:5433` по умолчанию. Внутри Compose-сети backend-контейнеры подключаются к хосту `database:5432`. Пароль в `docker/.env` для этого URL должен быть URL-безопасным (например, буквы, цифры и `_`). Не используйте примерный пароль вне локальной разработки.

## Импорт газет и таблиц

Поместите PDF/CSV/XLSX в `backend/app/newspaper_parser/data`, затем выполните:

```bash
docker compose --env-file docker/.env --profile ingest -f docker/compose.yaml run --build --rm parser
```

Парсер сохраняет текст PDF по страницам и агрегированные сводки CSV в `alfa_reports` и `alfa_report_chunks`. Исходные файлы удаляются после успешной записи всех материалов. Чтобы оставить файлы, добавьте `--keep-files` в конец команды:

```bash
docker compose --env-file docker/.env --profile ingest -f docker/compose.yaml run --build --rm parser python -m app.newspaper_parser.newspaper_parser --keep-files
```

Образ включает Tesseract с русским и английским языками для OCR сканированных PDF. Сам контейнер парсера имеет доступ на запись к каталогу `data`, так как парсер по умолчанию удаляет обработанные входные файлы.

## Остановка и данные

```bash
docker compose --env-file docker/.env -f docker/compose.yaml down
```

Команда сохраняет БД в именованном volume. **`docker compose down -v` удалит volume и все данные БД**; используйте её только если действительно хотите удалить контейнерную БД.

Настройки можно менять в `docker/.env`; `.env.example` предназначен только для локального запуска и не содержит рабочих секретов.
