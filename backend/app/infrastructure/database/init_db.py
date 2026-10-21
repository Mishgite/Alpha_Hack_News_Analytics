"""создаёт таблицы из schema.sql и проверяет наличие таблиц и триггера реакций"""

import argparse
import sys
from pathlib import Path

import psycopg
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database import models  # noqa: F401
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import get_engine

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def check_database(connection: Connection) -> int:
    """проверяет наличие таблиц приложения и включённого триггера реакций"""
    expected = set(Base.metadata.tables)
    existing = set(inspect(connection).get_table_names(schema="public"))
    missing = expected - existing
    if missing:
        raise ValueError("Missing tables: " + ", ".join(sorted(missing)))
    trigger_exists = connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger "
            "WHERE tgrelid = 'public.user_reactions'::regclass "
            "AND tgname = 'trg_reaction_totals' AND tgenabled IN ('O', 'A') "
            "AND NOT tgisinternal)"
        )
    )
    if not trigger_exists:
        raise ValueError("Missing or disabled trigger: trg_reaction_totals")
    return len(expected)


def initialize_database(engine: Engine) -> bool:
    """создаёт схему в пустой базе одной транзакцией, возвращает True при создании

    если таблицы уже есть, только проверяет их наличие и триггер
    при неполной схеме вызывает ValueError, существующие записи не меняет
    """
    with engine.begin() as connection:
        if inspect(connection).get_table_names(schema="public"):
            check_database(connection)
            return False

        search_path = connection.scalar(text("SHOW search_path"))
        # выполняем весь SQL через psycopg, чтобы сохранить тело функции с точками с запятой
        with connection.connection.driver_connection.cursor() as cursor:
            cursor.execute(SCHEMA_PATH.read_text(encoding="utf-8"), prepare=False)
            while cursor.nextset():
                pass
        connection.execute(
            text("SELECT pg_catalog.set_config('search_path', :path, false)"),
            {"path": search_path},
        )
        check_database(connection)
    return True


def main() -> int:
    """запускает создание схемы или проверку без записи при параметре --check"""
    parser = argparse.ArgumentParser(description="Create or check application tables")
    parser.add_argument(
        "--check", action="store_true", help="check without creating tables"
    )
    args = parser.parse_args()
    engine = None
    try:
        engine = get_engine()
        if not args.check:
            created = initialize_database(engine)
            print("Schema created" if created else "Schema already exists")
        with engine.connect() as connection:
            count = check_database(connection)
            print("Database:", connection.scalar(text("SELECT current_database()")))
            print("Tables:", count)
            print("Reaction trigger: OK")
        print("OK")
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (SQLAlchemyError, psycopg.Error):
        print(
            "PostgreSQL error: check the server, DATABASE_URL, permissions and PostgreSQL 17 version",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
