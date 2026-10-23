"""Впишите новость ниже и запустите файл: python manual_test.py.

Каждый запуск делает один платный запрос к Qwen. Автоповторов нет.
Настройки API берутся из backend/app/.env. В консоль выводятся полный JSON
с исходной новостью и тегами, затем отдельно список тегов.
"""

import json
from pathlib import Path
import sys

# ===== ВВОД: изменяйте значения здесь =====
DATA_TIME = "2026-10-23T12:00:00+03:00"  # Дата, время и часовой пояс.
TITLE = "В Москве открыли центр разработки"
TEXT = """
Компания открыла в Москве офис разработки программного обеспечения
для автоматизации бухгалтерского учета малого бизнеса.
""".strip()
# ===== КОНЕЦ ВВОДА =====


def main():
    # Прямой запуск из IDE или любой папки, без импорта остальных сервисов БД.
    if __package__:
        from .news_tagger import NewsTagger
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from ai_agents.news_tagger import NewsTagger

    try:
        result = NewsTagger().tag({
            "data-time": DATA_TIME,
            "title": TITLE,
            "text": TEXT,
        })
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2),
              file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Теги:", json.dumps(result["tags"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
