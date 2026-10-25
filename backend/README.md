# Backend

Python 3.12 · PostgreSQL 17

**[Настройка и запуск проекта](docs/run.md)**: окружение в `backend/app/.venv`, БД, импорт данных, API, фронтенд и воркер

- [Установка PostgreSQL и создание БД](docs/database-setup.md)
- [API: методы, параметры и ошибки](docs/api.md)
- [Сервисы: методы и использование](docs/services.md)
- [Импорт компаний](docs/import-companies.md)
- [Загрузка примеров новостей](docs/news-examples.md)
- [Воркер, источники и лимиты модели](docs/worker.md)
- [Фронтенд и GitHub Pages](../frontend/README.md)
- [Сторонние компоненты](THIRD_PARTY_NOTICES.md)

Код находится в `app/`, инструкции в `docs/`. Схемы Pydantic: `app/schemas/`; модели SQLAlchemy: `app/infrastructure/database/models/`

Локальные CSV, PDF и подготовленные тексты находятся в `data/` и исключены из Git. Окружение, `.env` и база данных также не передаются через Git
