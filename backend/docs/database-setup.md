# Локальная настройка backend

Требования: Python **3.12**, PostgreSQL **17.x**. Основной способ настройки и запуска: PyCharm.

## 1. Установить PostgreSQL

Если PostgreSQL 17 уже установлен, перейти к шагу 2.

1. Скачать **17.x / Windows x86-64** со [страницы PostgreSQL](https://www.postgresql.org/download/windows/).
2. В установщике выбрать **PostgreSQL Server**, **pgAdmin 4**, **Command Line Tools**. Stack Builder не требуется.
3. Оставить стандартные папки установки и хранения данных вне репозитория.
4. Задать пароль пользователя `postgres`, оставить порт `5432` и Locale по умолчанию.
5. После установки открыть `Win+R`, выполнить `services.msc`. Служба `postgresql-x64-17` должна иметь состояние «Выполняется».

[Документация по установке PostgreSQL в Windows](https://www.enterprisedb.com/docs/supported-open-source/postgresql/installing/windows/).

## 2. Выбрать интерпретатор и установить зависимости

1. Открыть настройки PyCharm и найти **Python Interpreter** через поиск.
2. Выбрать существующее окружение с Python **3.12**. Если его нет, через **Add Interpreter > Add Local Interpreter** создать **Virtualenv** на основе Python 3.12. Папка окружения может быть любой, например `backend/app/.venv`.
3. Для папки `backend` выбрать **Mark Directory as > Sources Root**.
4. Открыть `backend/app/requirements.txt`, нажать **Install requirements** в уведомлении редактора и дождаться установки.

Если уведомления нет, проверить в настройках **Python > Tools > Integrated Tools** поле **Package requirements file for SDK**: оно должно указывать на `backend/app/requirements.txt`. Также должна быть включена проверка **Unsatisfied package requirements** в **Editor > Inspections**.

Пакеты устанавливаются в выбранное окружение. [Интерпретатор проекта](https://www.jetbrains.com/help/pycharm/configuring-python-interpreter.html), [установка зависимостей](https://www.jetbrains.com/help/pycharm/managing-dependencies.html#install-the-required-packages-from-requirements-txt).

## 3. Создать базу alfa_news

Достаточно одного из двух вариантов. Если база `alfa_news` уже существует, перейти к шагу 4.

### Через pgAdmin

1. Открыть **pgAdmin 4** и подключиться к PostgreSQL 17 в дереве **Servers**.
2. Если сервера в списке нет: правой кнопкой по **Servers**, затем **Register > Server**. В **General > Name** указать `Local PostgreSQL`. В **Connection** заполнить:
   - **Host name/address**: `127.0.0.1`
   - **Port**: `5432`
   - **Maintenance database**: `postgres`
   - **Username**: `postgres`
   - **Password**: пароль из шага 1
3. Нажать **Save**, раскрыть подключённый сервер.
4. Правой кнопкой по **Databases**, затем **Create > Database**.
5. В **General > Database** указать `alfa_news`, в **Owner** выбрать `postgres`.
6. Нажать **Save**. База появится в списке **Databases**.

[Документация диалога создания базы в pgAdmin](https://www.pgadmin.org/docs/pgadmin4/latest/database_dialog.html).

### Через команду

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -X -h 127.0.0.1 -p 5432 -U postgres -d postgres -W -v ON_ERROR_STOP=1 -c "CREATE DATABASE alfa_news;"
```

Ввести пароль пользователя `postgres`. Ожидаемый результат: `CREATE DATABASE`.

## 4. Настроить подключение

1. В PyCharm скопировать `backend/app/.env.example` в ту же папку с именем `.env`.
2. В `DATABASE_URL` заменить `replace_with_local_password` на пароль PostgreSQL.
3. Проверить адрес `127.0.0.1`, порт `5432`, пользователя `postgres` и имя базы `alfa_news`. Сохранить файл.

Если `.env` уже существует, проверить его значения вместо копирования. Файл исключён из Git.

Специальные символы пароля в URL требуют кодирования, например `@` как `%40`. Для автоматического кодирования вместо копирования `.env.example` можно создать новый `.env` командой ниже. [Формат URL подключения](https://docs.sqlalchemy.org/en/20/core/engines.html#escaping-special-characters-such-as-at-signs-in-passwords).

<details>
<summary>Создание .env через PowerShell с кодированием пароля</summary>

Команда выполняется из папки `backend`. Путь `app/.venv/Scripts/python.exe` подходит для окружения в `backend/app/.venv`; при другом расположении заменить его путём из настроек Python Interpreter. Пароль вводится по запросу.

```powershell
& .\app\.venv\Scripts\python.exe -c "
from getpass import getpass
from pathlib import Path
from sqlalchemy import URL

path = Path('app/.env')
if path.exists():
    raise SystemExit('app/.env already exists')
url = URL.create(
    'postgresql+psycopg',
    username='postgres', password=getpass('PostgreSQL password: '),
    host='127.0.0.1', port=5432, database='alfa_news',
)
path.write_text('DATABASE_URL=' + url.render_as_string(hide_password=False) + '\n', encoding='utf-8')
print('Created app/.env')
"
```

Существующий `.env` не перезаписывается. При другом порте или адресе сервера заменить их в команде.

</details>

## 5. Создать таблицы кнопкой Run

1. Открыть **Run > Edit Configurations**, нажать **+ > Python**.
2. В поле **Name** указать `Создать таблицы`.
3. Переключить **Script path** на **Module name** и указать `app.infrastructure.database.init_db`.
4. В **Python interpreter** выбрать интерпретатор проекта из шага 2.
5. В **Working directory** выбрать папку `backend` этого репозитория.
6. Поле **Parameters** оставить пустым. Нажать **Apply > Run**.

Абсолютный путь к Python в команду вводить не требуется: используется выбранный интерпретатор. [Документация конфигурации запуска](https://www.jetbrains.com/help/pycharm/run-debug-configuration-python.html).

Модуль [init_db.py](../app/infrastructure/database/init_db.py) читает подключение из `app/.env` и выполняет [schema.sql](../app/infrastructure/database/schema.sql) одной транзакцией. Создаёт таблицы, связи, индексы и триггер счётчиков реакций.

Ожидаемый вывод:

```text
Schema created
Database: alfa_news
Tables: 31
Reaction trigger: OK
OK
```

При повторном запуске выводится `Schema already exists`, затем проверяется наличие таблиц и включённого триггера. Данные сохраняются. Если схема неполная, команда завершится с ошибкой. Этот модуль не обновляет структуру существующих таблиц.

Для просмотра в pgAdmin раскрыть **Databases > alfa_news > Schemas > public > Tables**. Если список пустой, выбрать **Refresh** в контекстном меню **Tables**. После создания схемы таблицы ещё не содержат данных приложения.

## 6. Проверка и повторный запуск

В **Run > Edit Configurations** скопировать конфигурацию `Создать таблицы`, назвать её `Проверить БД`, в **Parameters** указать `--check` и сохранить.

Для проверки выбрать `Проверить БД` и нажать **Run**. Создавать базу и окружение заново не требуется. После изменения зависимостей повторить установку из `requirements.txt` по шагу 2.

### Вариант для терминала

Для окружения, созданного именно в `backend/app/.venv`, из папки `backend`:

```powershell
& .\app\.venv\Scripts\python.exe -m app.infrastructure.database.init_db
& .\app\.venv\Scripts\python.exe -m app.infrastructure.database.init_db --check
```

Первая команда создаёт таблицы, вторая только проверяет. При другом расположении окружения заменить путь к `python.exe` на указанный в PyCharm. Терминал может использовать другой Python, поэтому наличие настроенного интерпретатора в IDE само по себе не определяет команду `python` в терминале.

HTTP-сервер пока не реализован. Для подключения API используются [сервисы](services.md). Работа внутри слоя хранения описана в [документации репозиториев](database-usage.md).

## Ошибки

- Не найден `psql.exe`: проверить папку установки PostgreSQL или создать базу через pgAdmin
- `PostgreSQL error`: проверить службу, пароль, порт, имя базы, права пользователя и версию PostgreSQL 17; проверить подключение к той же базе в pgAdmin
- `database alfa_news does not exist`: создать базу по шагу 3 на сервере из `app/.env`
- `app/.env already exists`: использовать существующий файл, сверив параметры подключения
- `database_url: Field required`: добавить `DATABASE_URL` в `app/.env`
- `No module named sqlalchemy` / `psycopg`: установить зависимости по шагу 2 в выбранное окружение
- `No module named app`: установить рабочую папку `backend`, в PyCharm запускать модуль из шага 5
- `Missing tables` / `Missing or disabled trigger`: схема неполная; `--check` ничего не создаёт, для пустой базы запустить конфигурацию из шага 5; для частично созданной схемы требуется исправить её отдельно
