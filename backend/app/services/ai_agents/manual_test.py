"""Впишите новость ниже и запустите файл: python manual_test.py.

Каждый запуск делает один платный запрос к Qwen. Автоповторов нет.
Настройки API берутся из backend/app/.env. В консоль выводятся полный JSON
с исходной новостью и тегами, затем отдельно список тегов.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# ===== ВВОД: изменяйте значения здесь =====
DATA_TIME = "2026-10-23T12:00:00+03:00"  # Дата, время и часовой пояс.
TITLE = "В Москве открыли центр разработки"
TEXT = """
Компания открыла в Москве офис разработки программного обеспечения
для автоматизации бухгалтерского учета малого бизнеса.
""".strip()
# ===== КОНЕЦ ВВОДА =====


def main():
    # прямой запуск из IDE использует тот же пакет app, что и сервисы
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from app.schemas.news import NewsForTagging
    from app.services.ai_agents import NewsTagger

    try:
        result = NewsTagger().tag(
            NewsForTagging(
                news_id=uuid4(),
                published_at=datetime.fromisoformat(DATA_TIME),
                title=TITLE,
                text=TEXT,
            )
        )
    except (ValueError, RuntimeError, OSError) as error:
        print(
            json.dumps({"error": str(error)}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 1

    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
