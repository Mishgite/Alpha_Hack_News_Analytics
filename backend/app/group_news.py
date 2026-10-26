"""группирует сохранённые новости без обращения к модели"""

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database.init_db import initialize_database
from app.infrastructure.database.session import get_engine
from app.services.news import NewsService


def main():
    """добавляет таблицу событий при обновлении проекта и группирует выбранный период"""
    parser = argparse.ArgumentParser(
        description="Group existing news without LLM calls"
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    initialize_database(get_engine())
    count = NewsService().group_existing_news(days=args.days, limit=args.limit)
    print(f"Проверено публикаций: {count}")


if __name__ == "__main__":
    main()
