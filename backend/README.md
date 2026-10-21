# Backend

Python 3.12 · PostgreSQL 17

## Настройка проекта

[Пошаговая инструкция](docs/database-setup.md): установка PostgreSQL, окружение, создание базы через pgAdmin или команду, подключение, создание таблиц через Python и настройка PyCharm

После настройки запуск выполняется кнопкой **Run** в PyCharm:

1. **Run > Edit Configurations > + > Python**
2. **Module name**: `app.infrastructure.database.init_db`
3. **Python interpreter**: выбранный интерпретатор проекта с Python 3.12
4. **Working directory**: папка `backend` этого репозитория
5. **Parameters**: пусто для создания таблиц, `--check` для проверки
6. **Apply > Run**

Окружение может находиться в любой папке. Путь `app/.venv` не обязателен. [Настройки запуска PyCharm](https://www.jetbrains.com/help/pycharm/run-debug-configuration-python.html).

## Работа с кодом

- [Сервисы: вызовы из API и обработчиков](docs/services.md)
- [Репозитории: операции с БД и транзакции](docs/database-usage.md)
- [Паттерны: где используются и зачем](docs/patterns.md)

Код находится в `app/`, документация в `docs/`. Модели Pydantic находятся в `app/schemas/`, модели таблиц SQLAlchemy в `app/infrastructure/database/models/`

Сейчас реализованы слои сервисов и БД. Команды запуска HTTP-сервера пока нет
