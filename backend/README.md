# Backend

Python 3.12 · PostgreSQL 17

- **[Настройка и запуск](docs/run.md)**: окружение, PostgreSQL, 50 компаний из CSV с LLM-разметкой, новости, отчёты, фронт и воркер
- [API](docs/api.md): запросы, параметры и ошибки
- [Сервисы](docs/services.md): методы и использование
- [Парсер источников](app/README_parser.md)
- [Сторонние компоненты](THIRD_PARTY_NOTICES.md)

Код: `app/`, Pydantic-схемы: `app/schemas/`, SQLAlchemy-модели: `app/infrastructure/database/models/`

CSV компаний, список выбранных ID, PDF, результаты импорта и `.env` хранятся локально и исключены из Git
