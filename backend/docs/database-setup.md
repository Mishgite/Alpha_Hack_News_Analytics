# Локальная настройка backend

Требования: Python **3.12**, PostgreSQL **17.x**. Основной способ настройки и запуска: PyCharm.

## После получения кода

1. В PyCharm выбрать **File > Open** и открыть корень репозитория `Alpha_Hack_News_Analytics`, в котором находятся `backend` и `frontend`.
2. При первой настройке выполнить шаги ниже. Окружение `.venv`, файл `.env` и локальная база не скачиваются при `git clone` или `git pull`.

Расположение локальных файлов:

```text
backend/
  app/
    .venv/             окружение Python, создаётся на каждом компьютере
    .env               подключение к локальной БД, создаётся вручную
    .env.example       образец из репозитория
    requirements.txt   зависимости из репозитория
```

## 1. Установить PostgreSQL

Если PostgreSQL 17 уже установлен, перейти к шагу 2.

1. Скачать **17.x / Windows x86-64** со [страницы PostgreSQL](https://www.postgresql.org/download/windows/).
2. В установщике выбрать **PostgreSQL Server**, **pgAdmin 4**, **Command Line Tools**. Stack Builder не требуется.
3. Оставить стандартные папки установки и хранения данных вне репозитория.
4. Задать пароль пользователя `postgres`, оставить порт `5432` и Locale по умолчанию.
5. После установки открыть `Win+R`, выполнить `services.msc`. Служба `postgresql-x64-17` должна иметь состояние «Выполняется».

[Документация по установке PostgreSQL в Windows](https://www.enterprisedb.com/docs/supported-open-source/postgresql/installing/windows/).

## 2. Создать окружение в backend/app/.venv

1. Открыть **Settings** и найти **Python Interpreter** через поиск.
2. Выбрать **Add Interpreter > Add Local Interpreter**, затем создание нового **Virtualenv**.
3. В **Base interpreter** выбрать установленный Python **3.12**.
4. В **Location** указать полный путь к папке окружения внутри своей копии проекта:

   ```text
   <корень репозитория>\backend\app\.venv
   ```

5. **Inherit packages from base interpreter** оставить выключенным. Нажать **OK / Create** и дождаться создания окружения.
6. Проверить, что интерпретатором проекта выбран:

   ```text
   <корень репозитория>\backend\app\.venv\Scripts\python.exe
   ```

7. Для папки `backend` выбрать **Mark Directory as > Sources Root**.
8. Открыть `backend/app/requirements.txt`, нажать **Install requirements** в уведомлении редактора и дождаться установки.

Если `.venv` уже создано, повторно его создавать не требуется: в **Add Local Interpreter** выбрать существующий интерпретатор по пути из пункта 6, затем установить зависимости.

Если кнопки **Install requirements** нет, в настройках **Python > Tools > Integrated Tools** указать `backend/app/requirements.txt` в поле **Package requirements file for SDK**. Проверка **Unsatisfied package requirements** должна быть включена в **Editor > Inspections**.

Все зависимости устанавливаются именно в выбранное окружение проекта. [Создание Virtualenv в PyCharm](https://www.jetbrains.com/help/pycharm/creating-virtual-environment.html), [установка зависимостей](https://www.jetbrains.com/help/pycharm/managing-dependencies.html#install-the-required-packages-from-requirements-txt).

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

## 5. Запустить создание таблиц

1. Открыть `backend/app/infrastructure/database/init_db.py` в PyCharm.
2. Правой кнопкой по файлу выбрать **Run 'init_db'**.

Используется интерпретатор проекта из шага 2. Настраивать Module name, Parameters или Working directory не требуется.

Модуль [init_db.py](../app/infrastructure/database/init_db.py) читает подключение из `app/.env` и выполняет [schema.sql](../app/infrastructure/database/schema.sql) одной транзакцией. Создаёт таблицы, связи, индексы и триггер счётчиков реакций.

Ожидаемый вывод:

```text
Schema created
Database: alfa_news
Tables: 31
Reaction trigger: OK
OK
```

При повторном запуске выводится `Schema already exists`, затем проверяется наличие таблиц и включённого триггера. Данные сохраняются. Если схема неполная, команда завершится с ошибкой. Для повторной проверки достаточно снова запустить тот же файл. Скрипт не обновляет структуру существующих таблиц.

Для просмотра в pgAdmin раскрыть **Databases > alfa_news > Schemas > public > Tables**. Если список пустой, выбрать **Refresh** в контекстном меню **Tables**. После создания схемы таблицы ещё не содержат данных приложения.

HTTP-сервер пока не реализован. Для подключения API используются [сервисы](services.md). Работа внутри слоя хранения описана в [документации репозиториев](database-usage.md).

## После следующих git pull

- Окружение `backend/app/.venv`, файл `backend/app/.env` и базу создавать заново не нужно
- Если изменился `requirements.txt`, повторить **Install requirements** из шага 2
- Изменение структуры БД требует отдельных инструкций к обновлению: `init_db.py` не обновляет существующие таблицы

## Ошибки

- Не найден `psql.exe`: проверить папку установки PostgreSQL или создать базу через pgAdmin
- `PostgreSQL error`: проверить службу, пароль, порт, имя базы, права пользователя и версию PostgreSQL 17; проверить подключение к той же базе в pgAdmin
- `database alfa_news does not exist`: создать базу по шагу 3 на сервере из `app/.env`
- `app/.env already exists`: использовать существующий файл, сверив параметры подключения
- `database_url: Field required`: добавить `DATABASE_URL` в `app/.env`
- `No module named sqlalchemy` / `psycopg`: установить зависимости по шагу 2 в выбранное окружение
- `Missing tables` / `Missing or disabled trigger`: схема создана частично или изменена; скрипт не исправляет существующую структуру автоматически
